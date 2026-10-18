import star.common.*;
import star.base.neo.*;
import star.cadmodeler.*;

public class starccm_record_cad extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();
        SolidModelManager smm = sim.get(SolidModelManager.class);
        CadModel cad = smm.createSolidModel(3);
        
        // List all methods on CadModel
        sim.println("=== CadModel ALL create/sketch methods ===");
        for (java.lang.reflect.Method method : cad.getClass().getMethods()) {
            String n = method.getName();
            if (n.startsWith("create") || n.contains("Sketch") || n.contains("sketch")) {
                sim.println("  " + n + "(" + method.getParameterCount() + ") -> " 
                    + java.util.Arrays.toString(method.getParameterTypes()));
            }
        }
    }
}
