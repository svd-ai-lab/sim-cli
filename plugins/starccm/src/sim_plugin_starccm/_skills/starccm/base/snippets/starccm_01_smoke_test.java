// 01_smoke_test.java — Verify Star-CCM+ connectivity
// Acceptance: exit_code == 0, JSON contains ok=true
import star.common.*;

public class starccm_01_smoke_test extends StarMacro {
    public void execute() {
        Simulation sim = getActiveSimulation();
        String title = sim.getPresentationName();
        sim.println("STARCCM_SMOKE=start");
        sim.println("STARCCM_TITLE=" + title);
        sim.println("{\"ok\": true, \"solver\": \"starccm\", \"title\": \"" + title + "\"}");
        sim.println("STARCCM_SMOKE=done");
    }
}
