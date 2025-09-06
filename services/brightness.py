import os

from gi.repository import GLib
from loguru import logger

from fabric.core.service import Property, Service, Signal
from fabric.utils import exec_shell_command_async, monitor_file


def exec_brightnessctl_async(args: str):
    exec_shell_command_async(f"brightnessctl {args}", lambda _: None)


# Discover screen backlight device
try:
    screen_device = os.listdir("/sys/class/backlight")
    screen_device = screen_device[0] if screen_device else ""
except FileNotFoundError:
    logger.warning("No backlight devices found, using VM compatibility mode")
    screen_device = ""

# Check if we're in a VM
def is_running_in_vm():
    try:
        with open("/sys/devices/virtual/dmi/id/product_name", "r") as f:
            product_name = f.read().strip().lower()
            if any(vm_name in product_name for vm_name in ["vmware", "virtualbox", "qemu", "kvm", "virtual", "vm"]):
                return True
    except (FileNotFoundError, IOError):
        pass
        
    try:
        with open("/proc/cpuinfo", "r") as f:
            cpuinfo = f.read().lower()
            if any(vm_name in cpuinfo for vm_name in ["vmware", "qemu", "kvm", "hypervisor"]):
                return True
    except (FileNotFoundError, IOError):
        pass
        
    return False

# Set VM mode if detected
vm_mode = is_running_in_vm()
if vm_mode and not screen_device:
    logger.info("VM detected, enabling brightness compatibility mode")
    # In VMs, we'll simulate brightness control


class Brightness(Service):
    """Service to manage screen brightness levels."""

    instance = None

    @staticmethod
    def get_initial():
        if Brightness.instance is None:
            Brightness.instance = Brightness()

        return Brightness.instance

    @Signal
    def screen(self, value: int) -> None:
        """Signal emitted when screen brightness changes."""
        # Implement as needed for your application

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # VM mode handling
        self.vm_mode = vm_mode
        self.simulated_brightness = 100  # Default brightness in VM mode
        
        # Path for screen backlight control
        self.screen_backlight_path = f"/sys/class/backlight/{screen_device}" if screen_device else ""

        # Initialize maximum brightness level
        if self.vm_mode and not screen_device:
            self.max_screen = 100  # Use percentage in VM mode
            logger.info("Using simulated brightness control for VM")
        else:
            self.max_screen = self.do_read_max_brightness(self.screen_backlight_path)

        if screen_device == "" and not self.vm_mode:
            return

        if screen_device:
            # Monitor screen brightness file
            self.screen_monitor = monitor_file(f"{self.screen_backlight_path}/brightness")

            self.screen_monitor.connect(
                "changed",
                lambda _, file, *args: self.emit(
                    "screen",
                    round(int(file.load_bytes()[0].get_data())),
                ),
            )
            
            # Log the initialization of the service
            logger.info(f"Brightness service initialized for device: {screen_device}")
        else:
            # Log VM mode initialization
            logger.info("Brightness service initialized in VM compatibility mode")

    def do_read_max_brightness(self, path: str) -> int:
        # Reads the maximum brightness value from the specified path.
        max_brightness_path = os.path.join(path, "max_brightness")
        if os.path.exists(max_brightness_path):
            with open(max_brightness_path) as f:
                return int(f.readline())
        return -1  # Return -1 if file doesn't exist, indicating an error.

    @Property(int, "read-write")
    def screen_brightness(self) -> int:
        # Property to get or set the screen brightness.
        if self.vm_mode and not screen_device:
            # In VM mode, return the simulated brightness
            return self.simulated_brightness
            
        brightness_path = os.path.join(self.screen_backlight_path, "brightness")
        if os.path.exists(brightness_path):
            with open(brightness_path) as f:
                return int(f.readline())
        logger.warning(f"Brightness file does not exist: {brightness_path}")
        return -1  # Return -1 if file doesn't exist, indicating error.

    @screen_brightness.setter
    def screen_brightness(self, value: int):
        # Setter for screen brightness property.
        if not (0 <= value <= self.max_screen):
            value = max(0, min(value, self.max_screen))

        try:
            if self.vm_mode and not screen_device:
                # In VM mode, just store the value and emit the signal
                self.simulated_brightness = value
                self.emit("screen", int((value / self.max_screen) * 100))
                logger.debug(f"VM brightness set to {value}%")
            else:
                # Normal hardware brightness control
                exec_brightnessctl_async(f"--device '{screen_device}' set {value}")
                self.emit("screen", int((value / self.max_screen) * 100))
        except GLib.Error as e:
            logger.error(f"Error setting screen brightness: {e.message}")
        except Exception as e:
            logger.exception(f"Unexpected error setting screen brightness: {e}")
