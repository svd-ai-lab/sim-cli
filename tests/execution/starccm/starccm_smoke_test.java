// Star-CCM+ smoke test macro
// Runs in batch mode — tests that starccm+ can compile and execute a macro
import star.common.*;

public class starccm_smoke_test extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();
        sim.println("STARCCM_SMOKE=start");
        sim.println("STARCCM_TITLE=" + sim.getPresentationName());
        sim.println("{\"ok\": true, \"solver\": \"starccm\", \"title\": \"" + sim.getPresentationName() + "\"}");
        sim.println("STARCCM_SMOKE=done");
    }
}
