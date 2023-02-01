.. _changelog:

Changelog
#########

*nanobind* uses a `semantic versioning <http://semver.org>`_ policy. Since the
current version is still in the prototype range (*0.x.y*), there are no (formal)
guarantees of API or ABI stability. That said, I will do my best to minimize
inconvenience whenever possible.

Version 0.1.1 (TBA)
-------------------------------
* Added casters for dense matrix/array types from the `Eigen library
  <https://eigen.tuxfamily.org/index.php?title=Main_Page>`_. (PR `#120
  <https://github.com/wjakob/nanobind/pull/120>`_).
* Implemented `nb::bind_vector<T>()` analogous to similar functionality in
  _pybind11_. (commit `f2df8a
  <https://github.com/wjakob/nanobind/commit/f2df8a90fbfb06ee03a79b0dd85fa0e266efeaa9>`_).
* Implemented `nb::bind_map<T>()` analogous to similar functionality in
  _pybind11_. (PR `#114 <https://github.com/wjakob/nanobind/pull/114>`_).
* Updated tuple/list iterator to satisfy the `std::forward_iterator` concept.
  (PR `#117 <https://github.com/wjakob/nanobind/pull/117>`_).
* Fixed issues with non-writeable tensors in NumPy. (commit `cc9cc1
  <https://github.com/wjakob/nanobind/commit/cc9cc11deb27f8b90bb1b57aaca0f303f87c2d8f>`_).
* Removed use of some C++20 features from the codebase. This now makes it
  possible to use _nanobind_ on  Visual Studio 2017 and GCC 7.3.1 (used on RHEL 7).
  (PR `#115 <https://github.com/wjakob/nanobind/pull/115>`_).
* Added the `nb::typed<...>` wrapper to override the type signature of an
  argument in a bound function in the generated docstring. (commit `3404c4
  <https://github.com/wjakob/nanobind/commit/3404c4f347981bce7f4c7a9bac762656bed8385>`_).
* Added an `nb::implicit_convertible<A, B>()`` function analogous to the one in
  _pybind11_. (commit `aba4af
  <https://github.com/wjakob/nanobind/commit/aba4af06992f14e21e5b7b379e7986e939316da4>`_).
* Updated `nb::make*_iterator<>` so that it returns references of elements, not
  copies. (commit `8916f5
  <https://github.com/wjakob/nanobind/commit/8916f51ad1a25318b5c9fcb07c153f6b72a43bd2>`_).
* Various minor fixes and improvements.
* Internals ABI version bump.

Version 0.1.0 (January 3, 2022)
-------------------------------

* Allow _nanobind_ methods on non-_nanobind) classes. (PR `#104
  <https://github.com/wjakob/nanobind/pull/104>`_).
* Fix dangling `tp_members` pointer in type initialization. (PR `#99
  <https://github.com/wjakob/nanobind/pull/99>`_).
* Added a runtime setting to suppress leak warnings. (PR `#109
  <https://github.com/wjakob/nanobind/pull/109>`_).
* Added the ability to hash ``nb::enum_<..>`` instances (PR `#106
  <https://github.com/wjakob/nanobind/pull/106>`_).
* Fixed the signature of ``nb::enum_<..>::export_values()``. (commit `714d17
  <https://github.com/wjakob/nanobind/commit/714d17e71aa405c7633e0bd798a8bdb7b8916fa1>`_).
* Double-check GIL status when performing reference counting operations in
  debug mode. (commit `a1b245
  <https://github.com/wjakob/nanobind/commit/a1b245fcf210fbfb10d7eb19dc2dc31255d3f561>`_).
* Fixed a reference leak that occurred when module initialization fails.
  (commit `adfa9e
  <https://github.com/wjakob/nanobind/commit/adfa9e547be5575f025d92abeae2e649a690760a>`_).
* Improved robustness of ``nb::tensor<..>`` caster. (commit `633672
  <https://github.com/wjakob/nanobind/commit/633672cd154c0ef13f96fee84c2291562f4ce3d3>`_).
* Upgraded the internally used ``tsl::robin_map<>`` hash table to address a
  rare `overflow issue <https://github.com/Tessil/robin-map/issues/52>`_
  discovered in this codebase. (commit `3b81b1
  <https://github.com/wjakob/nanobind/commit/3b81b18577e243118a659b524d4de9500a320312>`_).
* Various minor fixes and improvements.
* Internals ABI version bump.

Version 0.0.9 (Nov 23, 2022)
----------------------------

* PyPy 7.3.10 or newer is now supported subject to `certain limitations
  <https://github.com/wjakob/nanobind/blob/master/docs/pypy.rst>`_. (commits
  `f935f93
  <https://github.com/wjakob/nanobind/commit/f935f93b9d532a5ef1f385445f328d61eb2af97f>`_
  and `b343bbd
  <https://github.com/wjakob/nanobind/commit/b343bbd11c12b55bbc00492445c743cae18b298f>`_).
* Three changes that reduce the binary size and improve runtime performance of
  binding libraries. (commits `07b4e1fc
  <https://github.com/wjakob/nanobind/commit/07b4e1fc9e94eeaf5e9c2f4a63bdb275a25c82c6>`_,
  `9a803796
  <https://github.com/wjakob/nanobind/commit/9a803796cb05824f9df7593edb984130d20d3755>`_,
  and `cba4d285
  <https://github.com/wjakob/nanobind/commit/cba4d285f4e23b888dfcccc656c221414138a2b7>`_).
* Fixed a reference leak in ``python_error::what()`` (commit `61393ad
  <https://github.com/wjakob/nanobind/commit/61393ad3ce3bc68d195a1496422df43d5fb45ec0>`_).
* Adopted a new policy for function type annotations. (commit `c855c90 <https://github.com/wjakob/nanobind/commit/c855c90fc91d180f7c904c612766af6a84c017e3>`_).
* Improved the effectiveness of link-time-optimization when building extension modules
  with the ``NB_STATIC`` flag. This leads to smaller binaries. (commit `f64d2b9
  <https://github.com/wjakob/nanobind/commit/f64d2b9bb558afe28cf6909e4fa47ebf720f62b3>`_).
* Nanobind now relies on standard mechanisms to inherit the ``tp_traverse`` and
  ``tp_clear`` type slots instead of trying to reimplement the underlying
  CPython logic (commit `efa09a6b
  <https://github.com/wjakob/nanobind/commit/efa09a6bf6ac27f790b2c96389c2da42d4bc176b>`_).
* Moved nanobind internal data structures from ``builtins`` to Python
  interpreter state dictionary. (issue `#96
  <https://github.com/wjakob/nanobind/issues/96>`_, commit `ca23da7
  <https://github.com/wjakob/nanobind/commit/ca23da72ce71a45318f1e59474c9c2906fce5154>`_).
* Various minor fixes and improvements.


Version 0.0.8 (Oct 27, 2022)
----------------------------

* Caster for ``std::array<..>``. (commit `be34b16
  <https://github.com/wjakob/nanobind/commit/be34b165c6a0bed08e477755644f96759b9ed69a>`_).
* Caster for ``std::set<..>`` and ``std::unordered_set`` (PR `#87
  <https://github.com/wjakob/nanobind/pull/87>`_).
* Ported ``nb::make[_key_,_value]_iterator()`` from _pybind11_. (commit `34d0be1
  <https://github.com/wjakob/nanobind/commit/34d0be1bbeb54b8265456fd3a4a50e98f93fe6d4>`_).
* Caster for untyped ``void *`` pointers. (commit `6455fff
  <https://github.com/wjakob/nanobind/commit/6455fff7be5be2867063ea8138cf10e1d9f3065f>`_).
* Exploit move constructors in ``nb::class_<T>::def_readwrite()`` and
  ``nb::class_<T>::def_readwrite_static()`` (PR `#94
  <https://github.com/wjakob/nanobind/pull/94>`_).
* Redesign of the ``std::function<>`` caster to enable cyclic garbage collector
  traversal through inter-language callbacks (PR `#95
  <https://github.com/wjakob/nanobind/pull/95>`_).
* New interface for specifying custom type slots during Python type
  construction. (commit `38ba18a
  <https://github.com/wjakob/nanobind/commit/38ba18a835cfcd561efb4b4c640ee5c6d525decb>`_).
* Fixed potential undefined behavior related to ``nb_func`` garbage collection by
  Python's cyclic garbage collector. (commit `662e1b9
  <https://github.com/wjakob/nanobind/commit/662e1b9311e693f84c58799a67064d4a44bb706a>`_).
* Added a workaround for spurious reference leak warnings caused by other
  extension modules in conjunction with ``typing.py`` (commit `5e11e80
  <https://github.com/wjakob/nanobind/commit/5e11e8032f777c0a34abd437dc6e84a909907c91>`_).
* Various minor fixes and improvements.
* Internals ABI version bump.

Version 0.0.7 (Oct 14, 2022)
----------------------------

* Fixed a regression involving function docstrings in ``pydoc``. (commit
  `384f4a
  <https://github.com/wjakob/nanobind/commit/384f4ada1f3f08486fb03427227878ddbbcaad43>`_).

Version 0.0.6 (Oct 14, 2022)
----------------------------

* Fixed undefined behavior that could lead to crashes when nanobind types were
  freed. (commit `39266e
  <https://github.com/wjakob/nanobind/commit/39266ef0b0ccd7fa3e9237243a6c97ba8db2cd2a>`_).
* Refactored nanobind so that it works with ``Py_LIMITED_API`` (PR `#37 <https://github.com/wjakob/nanobind/pull/37>`_).
* Dynamic instance attributes (PR `#38 <https://github.com/wjakob/nanobind/pull/38>`_).
* Intrusive pointer support (PR `#43 <https://github.com/wjakob/nanobind/pull/43>`_).
* Byte string support (PR `#62 <https://github.com/wjakob/nanobind/pull/62>`_).
* Casters for ``std::variant<..>`` and ``std::optional<..>`` (PR `#67 <https://github.com/wjakob/nanobind/pull/67>`_).
* Casters for ``std::map<..>`` and ``std::unordered_map<..>`` (PR `#73 <https://github.com/wjakob/nanobind/pull/73>`_).
* Caster for ``std::string_view<..>`` (PR `#68 <https://github.com/wjakob/nanobind/pull/68>`_).
* Custom exception support (commit `41b7da <https://github.com/wjakob/nanobind/commit/41b7da33f1bc5c583bb98df66bdac2a058ec5c15>`_).
* Register nanobind functions with Python's cyclic garbage collector (PR `#86 <https://github.com/wjakob/nanobind/pull/86>`_).
* Various minor fixes and improvements.

Version 0.0.5 (May 13, 2022)
----------------------------

* Enumeration export.
* Implicit number conversion for numpy scalars.
* Various minor fixes and improvements.

Version 0.0.4 (May 13, 2022)
----------------------------

* Botched release, replaced by 0.0.5 on the same day.

Version 0.0.3 (Apr 14, 2022)
----------------------------

* DLPack support.
* Iterators for various Python type wrappers.
* Low-level interface to instance creation.
* Docstring generation improvements.
* Various minor fixes and improvements.

Version 0.0.2 (Mar 10, 2022)
----------------------------

* Initial release of the nanobind codebase.

Version 0.0.1 (Feb 21, 2022)
----------------------------

* Placeholder package on PyPI.
