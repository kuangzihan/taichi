import sys

from taichi._logging import *
from taichi.core import get_os_name, package_root, require_version
from taichi.core import ti_core as core
from taichi.lang import *  # pylint: disable=W0622 # TODO(archibate): It's `taichi.lang.core` overriding `taichi.core`
from taichi.main import main
from taichi.misc import *
from taichi.testing import *
from taichi.tools import *
from taichi.type import *

from taichi import ad
from taichi.ui import ui

# Issue#2223: Do not reorder, or we're busted with partially initialized module
from taichi import aot  # isort:skip

deprecated_names = {'SOA': 'Layout.SOA', 'AOS': 'Layout.AOS'}
if sys.version_info.minor < 7:
    for name, alter in deprecated_names.items():
        exec(f'{name} = {alter}')
else:

    def __getattr__(attr):
        if attr in deprecated_names:
            warning(
                f'ti.{attr} is deprecated. Please use ti.{deprecated_names[attr]} instead.',
                DeprecationWarning,
                stacklevel=2)
            exec(f'{attr} = {deprecated_names[attr]}')
            return locals()[attr]
        raise AttributeError(f"module '{__name__}' has no attribute '{attr}'")


__all__ = ['ad', 'core', 'misc', 'lang', 'tools', 'main', 'ui', 'profiler']

complex_kernel = deprecated('ti.complex_kernel',
                            'ti.ad.grad_replaced')(ad.grad_replaced)

complex_kernel_grad = deprecated('ti.complex_kernel_grad',
                                 'ti.ad.grad_for')(ad.grad_for)

__version__ = (core.get_version_major(), core.get_version_minor(),
               core.get_version_patch())
