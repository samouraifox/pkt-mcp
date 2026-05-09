import com.cisco.pt.ipc.IPCFactory;
import com.cisco.pt.ipc.ui.IPC;
import com.cisco.pt.ipc.enums.DeviceType;
import com.cisco.pt.ipc.sim.Device;
import com.cisco.pt.ipc.sim.Network;
import com.cisco.pt.ipc.ui.AppWindow;
import com.cisco.pt.ipc.ui.LogicalWorkspace;
import com.cisco.pt.ipc.ui.Workspace;
import com.cisco.pt.ptmp.PacketTracerSession;
import com.cisco.pt.ptmp.impl.PacketTracerSessionFactoryImpl;

public class Spike {
    public static void main(String[] args) throws Exception {
        String host = "localhost";
        int port = 39000;

        PacketTracerSession session = PacketTracerSessionFactoryImpl
                .getInstance()
                .openSession(host, port);

        IPCFactory factory = new IPCFactory(session);
        IPC ipc = factory.getIPC();
        AppWindow appWindow = factory.appWindow(ipc);
        Workspace workspace = factory.getActiveWorkspace(appWindow);
        LogicalWorkspace logical = factory.getLogicalWorkspace(workspace);

        String createdName = logical.addDevice(DeviceType.ROUTER, "2911", 200.0, 200.0);
        Network network = factory.getMainNetwork(appWindow.getActiveFile());
        Device router = network.getDevice(createdName);
        router.setName("R1");

        System.out.println("OK created=" + createdName + " renamed=R1");
        session.close();
    }
}
