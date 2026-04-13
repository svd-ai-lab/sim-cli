// Minimal Star-CCM+ Java macro for testing
import star.common.*;

public class SmokeTest extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();
        sim.println("STARCCM_VERSION=" + sim.getVersion());
        sim.println("{\"ok\": true, \"version\": \"21.02\"}");
    }
}
