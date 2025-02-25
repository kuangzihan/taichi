from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from taichi.lang import impl, kernel_impl
from taichi.lang._ndarray import Ndarray
from taichi.lang.field import ScalarField
from taichi.lang.matrix import MatrixField, MatrixNdarray, VectorNdarray
from taichi.type.annotations import ArgAnyArray, template


class KernelTemplate:
    def __init__(self, kernel_fn, aot_module):
        self._kernel_fn = kernel_fn
        self._aot_module = aot_module

    @staticmethod
    def keygen(v, key_p, fields):
        if isinstance(v, (int, float, bool)):
            key_p += '=' + str(v) + '/'
            return key_p
        for ky, val in fields:
            if (val is v):
                key_p += '=' + ky + '/'
                return key_p
        raise RuntimeError('Arg type must be of type int/float/boolean' +
                           'or taichi field. Type ' + str(type(v)) +
                           ' is not supported')

    def instantiate(self, **kwargs):
        name = self._kernel_fn.__name__
        kernel = self._kernel_fn._primal
        assert isinstance(kernel, kernel_impl.Kernel)
        injected_args = []
        key_p = ''
        anno_index = 0
        template_args = {}

        for index, (key, value) in enumerate(kwargs.items()):
            template_args[index] = (key, value)

        for anno in kernel.argument_annotations:
            if isinstance(anno, template):
                (k, v) = template_args[anno_index]
                key_p += k
                key_p = self.keygen(v, key_p, self._aot_module._fields.items())
                injected_args.append(v)
                anno_index += 1
            else:
                injected_args.append(0)
        kernel.ensure_compiled(*injected_args)
        self._aot_module._aot_builder.add_kernel_template(
            name, key_p, kernel.kernel_cpp)

        # kernel AOT
        self._aot_module._kernels.append(kernel)


class Module:
    """An AOT module to save and load Taichi kernels.

    This module serializes the Taichi kernels for a specific arch. The
    serialized module can later be loaded to run on that backend, without the
    Python environment.

    Example:
      Usage::

        m = ti.aot.Module(ti.metal)
        m.add_kernel(foo)
        m.add_kernel(bar)

        m.save('/path/to/module')

        # Now the module file '/path/to/module' contains the Metal kernels
        # for running ``foo`` and ``bar``.
    """
    def __init__(self, arch):
        """Creates a new AOT module instance

        Args:
          arch: Target backend architecture. This is ignored for now. The AOT
            backend still uses the one specified in :func:`~taichi.lang.init`.
        """
        self._arch = arch
        self._kernels = []
        self._fields = {}
        self._ndarrays = {}
        rtm = impl.get_runtime()
        rtm._finalize_root_fb_for_aot()
        self._aot_builder = rtm.prog.make_aot_module_builder(arch)

    def add_field(self, name, field):
        """Add a taichi field to the AOT module.

        Args:
          name: name of taichi field
          field: taichi field

        Example:
          Usage::

          a = ti.field(ti.f32, shape=(4,4))
          b = ti.field("something")

          m.add_field(a)
          m.add_field(b)

          # Must add in sequence
        """
        is_scalar = True
        self._fields[name] = field
        column_num = 1
        row_num = 1
        if isinstance(field, MatrixField):
            is_scalar = False
            row_num = field.m
            column_num = field.n
        else:
            assert isinstance(field, ScalarField)
        self._aot_builder.add_field(name, field.snode.ptr, is_scalar,
                                    field.dtype, field.snode.shape, row_num,
                                    column_num)

    def add_ndarray(self, name, arr):
        """Add a taichi ndarray to the AOT module.

        Args:
          name: name of taichi ndarray
          arr: taichi ndarray

        Example:
          Usage::

          a = ti.ndarray(ti.f32, shape=(4,4))

          m.add_ndarray(a)
        """
        is_scalar = True
        self._ndarrays[name] = arr
        column_num = 1
        row_num = 1
        if isinstance(arr, MatrixNdarray):
            is_scalar = False
            row_num = arr.m
            column_num = arr.n
        elif isinstance(arr, VectorNdarray):
            is_scalar = False
            column_num = arr.n
        else:
            assert isinstance(arr, Ndarray)
        self._aot_builder.add_ndarray(name, is_scalar, arr.dtype, arr.shape,
                                      row_num, column_num)

    def add_kernel(self, kernel_fn, example_any_arrays=(), name=None):
        """Add a taichi kernel to the AOT module.

        Args:
          kernel_fn (Function): the function decorated by taichi `kernel`.
          example_any_arrays (Tuple[any_arr]): a tuple of example any_arr inputs.
          name (str): Name to identify this kernel in the module. If not
            provided, uses the built-in ``__name__`` attribute of `kernel_fn`.

        """
        name = name or kernel_fn.__name__
        kernel = kernel_fn._primal
        assert isinstance(kernel, kernel_impl.Kernel)
        injected_args = []
        num_arr = len([
            anno for anno in kernel.argument_annotations
            if isinstance(anno, ArgAnyArray)
        ])
        assert num_arr == len(
            example_any_arrays
        ), f'Need {num_arr} example any_arr inputs but got {len(example_any_arrays)}'
        i = 0
        for anno in kernel.argument_annotations:
            if isinstance(anno, ArgAnyArray):
                # TODO: maybe also save example_any_arrays variable names?
                injected_args.append(example_any_arrays[i])
                i = i + 1
            else:
                # For primitive types, we can just inject a dummy value.
                injected_args.append(0)
        kernel.ensure_compiled(*injected_args)
        self._aot_builder.add(name, kernel.kernel_cpp)

        # kernel AOT
        self._kernels.append(kernel)

    @contextmanager
    def add_kernel_template(self, kernel_fn):
        """Add a taichi kernel (with template parameters) to the AOT module.

        Args:
          kernel_fn (Function): the function decorated by taichi `kernel`.

        Example:
          Usage::

            @ti.kernel
            def bar_tmpl(a: ti.template()):
              x = a
              # or y = a
              # do something with `x` or `y`

            m = ti.aot.Module(arch)
            with m.add_kernel_template(bar_tmpl) as kt:
              kt.instantiate(a=x)
              kt.instantiate(a=y)

            @ti.kernel
            def bar_tmpl_multiple_args(a: ti.template(), b: ti.template())
              x = a
              y = b
              # do something with `x` and `y`

            with m.add_kernel_template(bar_tmpl) as kt:
              kt.instantiate(a=x, b=y)

        TODO:
          * Support external array
        """
        kt = KernelTemplate(kernel_fn, self)
        yield kt

    def save(self, filepath, filename):
        """
        Args:
          filepath (str): path to a folder to store aot files.
          filename (str): filename prefix for stored aot files.
        """
        filepath = str(PurePosixPath(Path(filepath).resolve()))
        self._aot_builder.dump(filepath, filename)
