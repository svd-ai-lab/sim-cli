// Star-CCM+ macro that extends StarMacro but doesn't call getActiveSimulation
import star.common.*;

public class EmptyMacro extends StarMacro {
    public void execute() {
        System.out.println("No simulation used");
    }
}
