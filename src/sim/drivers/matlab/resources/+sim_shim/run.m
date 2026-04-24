function run(model, params_json, out_dir)
%SIM_SHIM.RUN Simulate a Simulink model and flatten outputs to disk.
%
%   sim_shim.run(model) runs MODEL with current parameters and saves the
%   resulting Simulink.SimulationOutput either as a Parquet timetable
%   (preferred) or a MAT file (fallback). The final line printed to
%   stdout is a JSON object carrying the artifact pointer:
%
%       {"ok": true, "result_file": "<path>", "format": "parquet|mat",
%        "signals": ["<name>", ...]}
%
%   sim_shim.run(model, params_json) decodes PARAMS_JSON as a JSON struct
%   and calls set_param(model, field, value) for each top-level field
%   before simulating. Typical use: {"StopTime":"10"}.
%
%   sim_shim.run(model, params_json, out_dir) writes artifacts under
%   OUT_DIR (created if missing). Defaults to a fresh tempname folder.
%
%   The function follows the MATLAB driver's "last JSON line on stdout"
%   convention. All intermediate prints are OK — parse_output() only
%   reads the final JSON object.

    if nargin < 2 || isempty(params_json)
        params_json = '{}';
    end
    if nargin < 3 || isempty(out_dir)
        out_dir = tempname;
    end
    if ~isfolder(out_dir)
        mkdir(out_dir);
    end

    modelName = char(model);
    params = jsondecode(char(params_json));
    if isstruct(params)
        fns = fieldnames(params);
        % TODO: set_param expects string values; numeric JSON values
        % decode to double and need num2str coercion. Phase A always
        % passes '{}' so this is not yet exercised.
        for i = 1:numel(fns)
            set_param(modelName, fns{i}, params.(fns{i}));
        end
    end

    simOut = sim(modelName);

    matPath = fullfile(out_dir, [modelName '_out.mat']);
    parquetPath = fullfile(out_dir, [modelName '_out.parquet']);
    resultFile = matPath;
    outputFormat = 'mat';
    signalNames = {};

    tt = local_to_timetable(simOut);
    wroteParquet = false;
    if ~isempty(tt) && exist('parquetwrite', 'file') == 2
        try
            parquetwrite(parquetPath, timetable2table(tt));
            resultFile = parquetPath;
            outputFormat = 'parquet';
            signalNames = tt.Properties.VariableNames;
            wroteParquet = true;
        catch
            wroteParquet = false;
        end
    end
    if ~wroteParquet
        save(matPath, 'simOut');
        if ~isempty(tt)
            signalNames = tt.Properties.VariableNames;
        end
    end

    payload = struct( ...
        'ok', true, ...
        'result_file', resultFile, ...
        'format', outputFormat, ...
        'signals', {signalNames});
    disp(jsonencode(payload));
end


function tt = local_to_timetable(simOut)
%LOCAL_TO_TIMETABLE Best-effort flatten SimulationOutput to a timetable.
%
%   Returns empty timetable.empty on any failure; caller falls back to
%   saving the raw SimulationOutput to MAT.

    tt = timetable.empty;
    if ~isa(simOut, 'Simulink.SimulationOutput')
        return;
    end
    try
        names = simOut.who;
    catch
        return;
    end
    for k = 1:numel(names)
        try
            v = simOut.(names{k});
        catch
            continue;
        end
        tt = local_merge_timeseries(tt, v, names{k});
        if isa(v, 'Simulink.SimulationData.Dataset')
            for i = 1:v.numElements
                el = v.getElement(i);
                if isprop(el, 'Values')
                    name = char(el.Name);
                    if isempty(name)
                        name = sprintf('%s_%d', names{k}, i);
                    end
                    tt = local_merge_timeseries(tt, el.Values, name);
                end
            end
        end
    end
end


function tt = local_merge_timeseries(tt, value, name)
    if isa(value, 'timeseries')
        try
            T = seconds(value.Time);
            data = squeeze(value.Data);
            if size(data, 1) ~= numel(T) && size(data, 2) == numel(T)
                data = data.';
            end
            new = timetable(T, data, 'VariableNames', {matlab.lang.makeValidName(name)});
            if isempty(tt)
                tt = new;
            else
                tt = synchronize(tt, new);
            end
        catch
            % Leave tt unchanged on conversion failure.
        end
    end
end
