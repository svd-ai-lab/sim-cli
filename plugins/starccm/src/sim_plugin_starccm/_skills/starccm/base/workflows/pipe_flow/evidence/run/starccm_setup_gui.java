// starccm_setup_gui.java — Run in GUI mode to create geometry with proper faces
// Usage: starccm+ starccm_setup_gui.java (GUI mode, no -batch)
// After this, use starccm_solve.java in batch mode to solve + export
import star.common.*;
import star.base.neo.*;
import star.meshing.*;
import star.cadmodeler.*;

public class starccm_setup_gui extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();
        sim.println("SETUP=start");

        try {
            // Create 3D-CAD part
            SolidModelManager smm = sim.get(SolidModelManager.class);
            sim.println("SolidModelManager class: " + smm.getClass().getName());

            // Try creating with dimension = 3
            CadModel cad = smm.createSolidModel(3);
            cad.setPresentationName("Channel");

            // List available methods on CadModel for box creation
            sim.println("=== CadModel methods containing 'box' or 'Block' or 'create' ===");
            for (java.lang.reflect.Method method : cad.getClass().getMethods()) {
                String name = method.getName().toLowerCase();
                if (name.contains("box") || name.contains("block") ||
                    (name.contains("create") && method.getParameterCount() <= 3)) {
                    sim.println("  " + method.getName() + " params=" + method.getParameterCount()
                        + " types=" + java.util.Arrays.toString(method.getParameterTypes()));
                }
            }

        } catch (Exception e) {
            sim.println("ERROR: " + e.getClass().getName() + ": " + e.getMessage());
            e.printStackTrace(new java.io.PrintWriter(System.out));
        }

        sim.println("SETUP=done");
    }
}
