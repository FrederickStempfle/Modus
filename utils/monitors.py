import json
import warnings
import os
import subprocess
from typing import Dict
import time
from fabric.hyprland import Hyprland
from gi.repository import Gdk
from functools import lru_cache
from loguru import logger

warnings.filterwarnings("ignore", category=DeprecationWarning)

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
VM_MODE = is_running_in_vm()
if VM_MODE:
    logger.info("VM detected, enabling monitor compatibility mode")


def ttl_lru_cache(seconds_to_live: int, maxsize: int = 128):
    def wrapper(func):
        @lru_cache(maxsize)
        def inner(__ttl, *args, **kwargs):
            return func(*args, **kwargs)

        return lambda *args, **kwargs: inner(
            time.time() // seconds_to_live, *args, **kwargs
        )

    return wrapper


class HyprlandWithMonitors(Hyprland):
    """A Hyprland class with additional monitor common."""

    instance = None

    @staticmethod
    def get_default():
        if HyprlandWithMonitors.instance is None:
            HyprlandWithMonitors.instance = HyprlandWithMonitors()

        return HyprlandWithMonitors.instance

    def __init__(self, commands_only: bool = False, **kwargs):
        self.display: Gdk.Display = Gdk.Display.get_default()
        self.vm_mode = VM_MODE
        super().__init__(commands_only, **kwargs)
        
        if self.vm_mode:
            logger.info("Using VM-compatible monitor detection")

    @ttl_lru_cache(100, 5)
    def get_all_monitors(self) -> Dict:
        try:
            monitors = json.loads(self.send_command("j/monitors").reply)
            return {monitor["id"]: monitor["name"] for monitor in monitors}
        except Exception as e:
            if self.vm_mode:
                # In VM mode, provide a fallback monitor
                logger.warning(f"Error getting monitors in VM, using fallback: {e}")
                return {0: "XWAYLAND0"}
            else:
                logger.error(f"Error getting monitors: {e}")
                return {}

    def get_gdk_monitor_id_from_name(self, plug_name: str) -> int | None:
        try:
            for i in range(self.display.get_n_monitors()):
                try:
                    if self.display.get_default_screen().get_monitor_plug_name(i) == plug_name:
                        return i
                except Exception:
                    # Some monitors might not have plug names in VMs
                    pass
            
            # Fallback for VM environments
            if self.vm_mode:
                return 0  # Return the primary monitor in VM mode
            return None
        except Exception as e:
            logger.error(f"Error in get_gdk_monitor_id_from_name: {e}")
            if self.vm_mode:
                return 0
            return None

    def get_gdk_monitor_id(self, hyprland_id: int) -> int | None:
        try:
            monitors = self.get_all_monitors()
            if hyprland_id in monitors:
                return self.get_gdk_monitor_id_from_name(monitors[hyprland_id])
            
            # Fallback for VM environments
            if self.vm_mode:
                return 0
            return None
        except Exception as e:
            logger.error(f"Error in get_gdk_monitor_id: {e}")
            if self.vm_mode:
                return 0
            return None

    def get_current_gdk_monitor_id(self) -> int | None:
        try:
            active_workspace = json.loads(self.send_command("j/activeworkspace").reply)
            return self.get_gdk_monitor_id_from_name(active_workspace["monitor"])
        except Exception as e:
            logger.error(f"Error in get_current_gdk_monitor_id: {e}")
            if self.vm_mode:
                return 0
            return None
