#!/usr/bin/env python3
"""
stubgen.py: nanobind stub generation tool

This file provides both an API (``nanobind.stubgen.StubGen``) and a command
line interface to generate stubs for nanobind extensions.

To generate stubs on the command line, invoke the stub generator with a module
name, which will place the newly generated ``.pyi`` file directly into the
module folder.

```
python -m nanobind.stubgen <module name>
```

Specify ``-o <filename>`` or ``-O <path>`` to redirect the output somewhere
else in case this is not desired.

To programmatically generate stubs, construct an instance of the ``StubGen``
class and repeatedly call ``.put()`` to register modules or contents within the
modules (specific methods, classes, etc.). Afterwards, the ``.get()`` method
returns a string containing the stub declarations.

```
from nanobind.stubgen import StubGen
import my_module

sg = StubGen()
sg.put(my_module)
print(sg.get())
```

Internally, stub generation involves two potentially complex steps: converting
nanobind overload chains into '@overload' declarations that can be understood
by the 'typing' module, and turning default values back into Python
expressions. To make this process more well-defined, the implementation relies
on an internal ``__nb_signature__`` property that nanobind functions expose
specifically to simplify stub generation.

(Note that for now, the StubGen API is considered experimental and not subject
 to the semantic versioning policy used by the nanobind project.)
"""

from inspect import Signature, Parameter, signature, ismodule, getmembers
import textwrap
import importlib
import importlib.machinery
import types
import typing
import re
import sys

# Standard operations supported by arithmetic enumerations
# fmt: off
ENUM_OPS = [
    "add", "sub", "mul", "floordiv", "eq", "ne", "gt", "ge", "lt", "le",
    "index", "repr", "hash", "int", "rshift", "lshift", "and", "or", "xor",
    "neg", "abs", "invert",
]  # fmt: on


class StubGen:
    def __init__(
        self,
        include_docstrings=True,
        include_private=False,
        module=None,
        max_expr_length=50,
        patterns={},
    ):
        # Store the module (if available) so that we can check for naming
        # conflicts when introducing temporary variables needed within the stub
        self.module = module

        # Should docstrings be included in the generated stub?
        self.include_docstrings = include_docstrings

        # Should private members (that start or end with
        # a single underscore) be included?
        self.include_private = include_private

        # Maximal length (in characters) before an expression gets abbreviated as '...'
        self.max_expr_length = max_expr_length

        # Replacement patterns
        self.patterns = patterns

        # ---------- Internal fields ----------

        # Current depth / indentation level
        self.depth = 0

        # Output will be appended to this string
        self.output = ""

        # A stack to avoid infinite recursion
        self.stack = []

        # An associated sequence of identifier
        self.prefix = module.__name__ if module else ""

        # Dictionary to keep track of import directives added by the stub generator
        self.imports = {}

        # Negative lookbehind matching word boundaries except '.'
        sep_before = r"(?<![\\B\.])"

        # Negative lookforward matching word boundaries except '.'
        sep_after = r"(?![\\B\.])"

        # Positive lookforward matching an opening bracket
        bracket = r"(?=\[)"

        # Regexp matching a Python identifier
        identifier = r"[^\d\W]\w*"

        # Regexp matching a sequence of identifiers separated by periods
        identifier_seq = (
            sep_before
            + "((?:"
            + identifier
            + r"\.)+)("
            + identifier
            + r")\b"
            + sep_after
        )

        # Precompile a regular expression used to extract types from 'typing.*'
        self.typing_re = re.compile(
            sep_before + r"(Union|Optional|Tuple|Dict|List|Annotated)" + bracket
        )

        # ditto, for 'typing.*' or 'collections.abc.*' depending on the Python version
        self.abc_re = re.compile(
            sep_before + r"(Callable|Tuple|Sequence|Mapping|Set|Iterator|Iterable)\b"
        )

        # Precompile a regular expression used to extract types from 'types.*'
        self.types_re = re.compile(
            sep_before + r"(ModuleType|CapsuleType|EllipsisType)\b"
        )

        # Precompile a regular expression used to extract nanobind nd-arrays
        self.ndarray_re = re.compile(
            sep_before + r"(numpy\.ndarray|ndarray|torch\.Tensor)\[([^\]]*)\]"
        )

        # Regular expression matching `builtins.*` types
        self.none_re = re.compile(sep_before + r"builtins\.(None)Type\b")
        self.builtins_re = re.compile(sep_before + r"builtins\.(" + identifier + ")")

        # Precompile a regular expression used to extract a few other types
        self.identifier_seq_re = re.compile(identifier_seq)

        # Regular expression to strip away the module for locals
        if self.module:
            module_name_re = self.module.__name__.replace(".", r"\.")
            self.module_member_re = re.compile(
                sep_before + module_name_re + r"\.(" + identifier + ")" + sep_after
            )
        else:
            self.module_member_re = None

        # Should we insert a dummy base class to handle enumerations?
        self.abstract_enum = False
        self.abstract_enum_arith = False

    def write(self, s):
        """Append raw characters to the output"""
        self.output += s

    def write_ln(self, line):
        """Append an indented line"""
        if len(line) != 0 and not line.isspace():
            self.output += "    " * self.depth + line
        self.output += "\n"

    def write_par(self, line):
        """Append an indented paragraph"""
        self.output += textwrap.indent(line, "    " * self.depth)

    def put_docstr(self, docstr):
        """Append an indented single or multi-line docstring"""
        docstr = textwrap.dedent(docstr).strip()
        raw_str = ""
        if "''" in docstr or "\\" in docstr:
            # Escape all double quotes so that no unquoted triple quote can exist
            docstr = docstr.replace("''", "\\'\\'")
            raw_str = "r"
        if len(docstr) > 70 or "\n" in docstr:
            docstr = "\n" + docstr + "\n"
        docstr = f'{raw_str}"""{docstr}"""\n'
        self.write_par(docstr)

    def put_nb_overload(self, fn, sig, name=None):
        """Append an 'nb_func' function overload"""
        sig_str, docstr, start = sig[0], sig[1], 0
        if sig_str.startswith("def (") and name is not None:
            sig_str = "def " + name + sig_str[4:]

        sig_str = self.replace_standard_types(sig_str)

        # Render function default arguments
        for index, arg in enumerate(sig[2:]):
            pos = -1
            custom_signature = False
            pattern = None

            # First, handle the case where the user overrode the default value signature
            if isinstance(arg, str):
                pattern = f"\\={index}"
                pos = sig_str.find(pattern, start)
                if pos >= 0:
                    custom_signature = True

            # General case
            if pos < 0:
                pattern = f"\\{index}"
                pos = sig_str.find(pattern, start)

            if pos < 0:
                raise Exception(
                    "Could not locate default argument in function signature"
                )

            if custom_signature:
                arg_str = arg
            else:
                arg_str = self.expr_str(arg)
                if arg_str is None:
                    arg_str = "..."

            assert (
                "\n" not in arg_str
            ), "Default argument string may not contain newlines."

            assert pattern is not None
            sig_str = sig_str[:pos] + arg_str + sig_str[pos + len(pattern) :]
            start = pos + len(arg_str)

        if type(fn).__name__ == "nb_func" and self.depth > 0:
            self.write_ln("@staticmethod")

        if not docstr or not self.include_docstrings:
            for s in sig_str.split("\n"):
                self.write_ln(s)
            self.output = self.output[:-1] + ": ...\n"
        else:
            docstr = textwrap.dedent(docstr)
            for s in sig_str.split("\n"):
                self.write_ln(s)
            self.output = self.output[:-1] + ":\n"
            self.depth += 1
            self.put_docstr(docstr)
            self.depth -= 1
        self.write("\n")

    def put_nb_func(self, fn, name=None):
        """Append an 'nb_func' function object"""
        sigs = fn.__nb_signature__
        count = len(sigs)
        assert count > 0
        if count == 1:
            self.put_nb_overload(fn, sigs[0], name)
        else:
            overload = self.import_object("typing", "overload")
            for s in sigs:
                self.write_ln(f"@{overload}")
                self.put_nb_overload(fn, s, name)

    def put_function(self, fn, name=None, parent=None):
        """Append a function of an arbitrary type"""
        # Don't generate a constructor for nanobind classes that aren't constructible
        if name == "__init__" and type(parent).__name__.startswith("nb_type"):
            return

        if self.module:
            fn_module = getattr(fn, "__module__", None)
            fn_name = getattr(fn, "__name__", None)

            # Check if this function is an alias from another module
            if fn_module and fn_module != self.module.__name__:
                self.put_value(fn, name, None)
                return

            # Check if this function is an alias from the same module
            if name and fn_name and name != fn_name:
                self.write_ln(f"{name} = {fn_name}\n")
                return

        if isinstance(fn, staticmethod):
            self.write_ln('@staticmethod')
            fn = fn.__func__
        elif isinstance(fn, classmethod):
            self.write_ln('@staticmethod')
            fn = fn.__func__

        # Special handling for nanobind functions with overloads
        if type(fn).__module__ == "nanobind":
            self.put_nb_func(fn, name)
            return

        if name is None:
            name = fn.__name__

        overloads = []
        if hasattr(fn, '__module__'):
            if sys.version_info >= (3, 11, 0):
                overloads = typing.get_overloads(fn)
            else:
                try:
                    import typing_extensions
                    overloads = typing_extensions.get_overloads(fn)
                except ModuleNotFoundError:
                    raise RuntimeError("stubgen.py requires the 'typing_extension' package on Python <3.11")
        if not overloads:
            overloads = [fn]

        for i, fno in enumerate(overloads):
            if len(overloads) > 1:
                overload = self.import_object("typing", "overload")
                self.write_ln(f'@{overload}')

            sig_str = f"{name}{self.signature_str(signature(fno))}"

            # Potentially copy docstring from the implementation function
            docstr = fno.__doc__
            if i == 0 and not docstr and fn.__doc__:
                docstr = fn.__doc__

            if not docstr or not self.include_docstrings:
                self.write_ln("def " + sig_str + ": ...")
            else:
                self.write_ln("def " + sig_str + ":")
                self.depth += 1
                self.put_docstr(docstr)
                self.depth -= 1
            self.write("\n")

    def put_property(self, prop, name):
        """Append a Python 'property' object"""
        fget, fset = prop.fget, prop.fset
        self.write_ln("@property")
        self.put(fget, name=name)
        if fset:
            self.write_ln(f"@{name}.setter")
            docstrings_backup = self.include_docstrings
            if (
                type(fget).__module__ == "nanobind"
                and type(fset).__module__ == "nanobind"
            ):
                doc1 = fget.__nb_signature__[0][1]
                doc2 = fset.__nb_signature__[0][1]
                if doc1 and doc2 and doc1 == doc2:
                    self.include_docstrings = False
            self.put(prop.fset, name=name)
            self.include_docstrings = docstrings_backup

    def put_nb_static_property(self, name, prop):
        """Append an 'nb_static_property' object"""
        getter_sig = prop.fget.__nb_signature__[0][0]
        getter_sig = getter_sig[getter_sig.find("/) -> ") + 6 :]
        self.write_ln(f"{name}: {getter_sig} = ...")
        if prop.__doc__ and self.include_docstrings:
            self.put_docstr(prop.__doc__)
        self.write("\n")

    def put_type(self, tp, module, name):
        """Append a 'nb_type' type object"""
        if name and (name != tp.__name__ or module.__name__ != tp.__module__):
            if module.__name__ == tp.__module__:
                # This is an alias of a type in the same module
                alias_tp = self.import_object("typing", "TypeAlias")
                self.write_ln(f"{name}: {alias_tp} = {tp.__name__}\n")
            else:
                # Import from a different module
                self.put_value(tp, name, None)
        else:
            is_enum = self.is_enum(tp)
            docstr = tp.__doc__
            tp_dict = dict(tp.__dict__)
            tp_bases = None

            if is_enum:
                # Rewrite enumerations so that they derive from a helper
                # type to avoid bloat from a large number of repeated
                # function declaarations

                docstr = docstr.__doc__
                is_arith = "__add__" in tp_dict
                self.abstract_enum = True
                self.abstract_enum_arith |= is_arith

                tp_bases = ["_Enum" + ("Arith" if is_arith else "")]
                del tp_dict["name"]
                del tp_dict["value"]
                for op in ENUM_OPS:
                    name, rname = f"__{op}__", f"__r{op}__"
                    if name in tp_dict:
                        del tp_dict[name]
                    if rname in tp_dict:
                        del tp_dict[rname]

            if "__nb_signature__" in tp.__dict__:
                # Types with a custom signature override
                for s in tp.__nb_signature__.split("\n"):
                    self.write_ln(self.replace_standard_types(s))
                self.output = self.output[:-1] + ":\n"
            else:
                self.write_ln(f"class {tp.__name__}:")
                if tp_bases is None:
                    tp_bases = getattr(tp, "__orig_bases__", None)
                    if tp_bases is None:
                        tp_bases = tp.__bases__
                    tp_bases = [self.type_str(base) for base in tp_bases]

                if tp_bases != ["object"]:
                    self.output = self.output[:-2] + "("
                    for i, base in enumerate(tp_bases):
                        if i:
                            self.write(", ")
                        self.write(base)
                    self.write("):\n")

            self.depth += 1
            output_len = len(self.output)
            if docstr and self.include_docstrings:
                self.put_docstr(docstr)
                if len(tp_dict):
                    self.write("\n")
            for k, v in tp_dict.items():
                self.put(v, module, k, tp)
            if output_len == len(self.output):
                self.write_ln("pass\n")
            self.depth -= 1

    def is_enum(self, tp):
        """Check if the given type is an enumeration"""
        return hasattr(tp, "@entries")

    def is_function(self, tp):
        return (
            issubclass(tp, types.FunctionType)
            or issubclass(tp, types.BuiltinFunctionType)
            or issubclass(tp, types.BuiltinMethodType)
            or issubclass(tp, types.WrapperDescriptorType)
            or issubclass(tp, staticmethod)
            or issubclass(tp, classmethod)
            or (tp.__module__ == "nanobind" and tp.__name__ == "nb_func")
        )

    def put_value(self, value, name, parent, abbrev=True):
        tp = type(value)
        is_function = self.is_function(tp)
        is_enum_entry = (
            isinstance(parent, type) and issubclass(tp, parent) and self.is_enum(parent)
        )

        if is_enum_entry:
            self.write_ln(f"{name}: {self.type_str(tp)}")
            if value.__doc__ and self.include_docstrings:
                self.put_docstr(value.__doc__)
            self.write("\n")
        elif is_function or isinstance(value, type):
            self.import_object(value.__module__, value.__name__, name)
        else:
            value_str = self.expr_str(value, abbrev)
            if value_str is None:
                value_str = "..."

            if issubclass(tp, typing.TypeVar) or \
               (hasattr(typing, 'TypeVarTuple') and
                issubclass(tp, typing.TypeVarTuple)):
                self.write_ln(f"{name} = {value_str}\n")
            else:
                self.write_ln(f"{name}: {self.type_str(tp)} = {value_str}\n")

    def replace_standard_types(self, s):
        """Detect standard types (e.g. typing.Optional) within a type signature"""

        # Strip module from types declared in the same module
        is_local = False
        if self.module_member_re:
            s_old = s
            s = self.module_member_re.sub(lambda m: m.group(1), s)
            is_local = s != s_old

        # Remove 'builtins.*'
        s = self.none_re.sub(lambda m: m.group(1), s)
        s = self.builtins_re.sub(lambda m: m.group(1), s)

        # tuple[] is not a valid type annotation
        s = s.replace("tuple[]", "tuple[()]").replace("Tuple[]", "Tuple[()]")

        # Rewrite typings/collection.abc types
        s = self.typing_re.sub(lambda m: self.import_object("typing", m.group(1)), s)
        source_pkg = "typing" if sys.version_info < (3, 9, 0) else "collections.abc"
        s = self.abc_re.sub(lambda m: self.import_object(source_pkg, m.group(1)), s)

        # Import a few types from 'types.*' as needed
        s = self.types_re.sub(lambda m: self.import_object("types", m.group(1)), s)

        # Process nd-array type annotations so that MyPy accepts them
        def replace_ndarray(m):
            s = m.group(2)

            ndarray = self.import_object("numpy.typing", "ArrayLike")
            s = re.sub(r"dtype=([\w]*)\b", r"dtype='\g<1>'", s)
            s = s.replace("*", "None")

            if s:
                annotated = self.import_object("typing", "Annotated")
                return f"{annotated}[{ndarray}, dict({s})]"
            else:
                return ndarray

        s = self.ndarray_re.sub(replace_ndarray, s)

        # For types from other modules, add suitable import statements
        def ensure_module_imported(m):
            self.import_object(m.group(1)[:-1], None)
            return m.group(0)

        if not is_local:
            s = self.identifier_seq_re.sub(ensure_module_imported, s)

        return s

    def put(self, value, module=None, name=None, parent=None):
        # Avoid infinite recursion due to cycles
        old_prefix = self.prefix

        if value in self.stack:
            return
        try:
            self.stack.append(value)

            if self.prefix and name:
                self.prefix = self.prefix + "." + name
            else:
                self.prefix = name if name else self.prefix

            # Check if an entry in a provided pattern file matches
            if self.prefix:
                for query, query_v in self.patterns.items():
                    match = query.search(self.prefix)
                    if not match:
                        continue

                    query_v[1] += 1
                    for l in query_v[0]:
                        ls = l.strip()
                        if ls == "\\doc":
                            # Docstring reference
                            tp = type(value)
                            if tp.__module__ == "nanobind" and tp.__name__ in (
                                "nb_func",
                                "nb_method",
                            ):
                                for tp_i in value.__nb_signature__:
                                    doc = tp_i[1]
                                    if doc:
                                        break
                            else:
                                doc = getattr(value, "__doc__", None)
                            self.depth += 1
                            if doc and self.include_docstrings:
                                self.put_docstr(doc)
                            else:
                                self.write_ln("pass")
                            self.depth -= 1
                            continue
                        elif ls.startswith("\\from "):
                            items = ls[5:].split(" import ")
                            if len(items) != 2:
                                raise RuntimeError(
                                    f"Could not parse import declaration {ls}"
                                )
                            for item in items[1].strip("()").split(","):
                                item = item.split(" as ")
                                import_module, import_name = (
                                    items[0].strip(),
                                    item[0].strip(),
                                )
                                import_as = item[1].strip() if len(item) > 1 else None
                                self.import_object(
                                    import_module, import_name, import_as
                                )
                            continue

                        groups = match.groups()
                        for i in reversed(range(len(groups))):
                            l = l.replace(f"\\{i+1}", groups[i])
                        for k, v in match.groupdict():
                            l = l.replace(f"\\{k}", v)
                        self.write_ln(l)
                    return

            # Don't explicitly include various standard elements found
            # in modules, classes, etc.
            if name in (
                "__doc__",
                "__module__",
                "__name__",
                "__new__",
                "__builtins__",
                "__cached__",
                "__path__",
                "__version__",
                "__spec__",
                "__loader__",
                "__package__",
                "__nb_signature__",
                "__class_getitem__",
                "__orig_bases__",
                "__file__",
                "__dict__",
                "__weakref__",
                "@entries",
            ):
                return

            tp = type(value)

            # Potentially exclude private members
            if (
                not self.include_private
                and name
                # Need these even if their name indicates otherwise
                and not issubclass(tp, typing.TypeVar)
                and not (
                    hasattr(typing, "TypeVarTuple")
                    and issubclass(tp, typing.TypeVarTuple)
                )
                and len(name) > 2
                and (
                    (name[0] == "_" and name[1] != "_")
                    or (name[-1] == "_" and name[-2] != "_")
                )
            ):
                return

            tp_mod, tp_name = tp.__module__, tp.__name__

            if ismodule(value):
                if len(self.stack) != 1:
                    # Do not recurse into submodules, but include a directive to import them
                    self.import_object(value.__name__, name=None, as_name=name)
                    return
                for name, child in getmembers(value):
                    self.put(child, module=value, name=name, parent=value)
            elif self.is_function(tp):
                self.put_function(value, name, parent)
            elif issubclass(tp, type):
                self.put_type(value, module, name)
            elif tp_mod == "nanobind":
                if tp_name == "nb_method":
                    self.put_nb_func(value, name)
                elif tp_name == "nb_static_property":
                    self.put_nb_static_property(name, value)
            elif tp_mod == "builtins":
                if tp is property:
                    self.put_property(value, name)
                else:
                    abbrev = name != "__all__"
                    self.put_value(value, name, parent, abbrev=abbrev)
            else:
                self.put_value(value, name, parent)
        finally:
            self.stack.pop()
            self.prefix = old_prefix

    def import_object(self, module, name, as_name=None):
        """
        Import a type (e.g. typing.Optional) used within the stub, ensuring
        that this does not cause conflicts. Specify ``as_name`` to ensure that
        the import is bound to a specified name.
        """
        if module == "builtins" and (not as_name or name == as_name):
            return name

        # Rewrite module name if this is relative import from a submodule
        if self.module and module.startswith(self.module.__name__):
            module_short = module[len(self.module.__name__) :]
            if not name and as_name and module_short[0] == ".":
                name = as_name = module_short[1:]
                module_short = "."
        else:
            module_short = module

        # Query a cache of previously imported objects
        imports_module = self.imports.get(module_short, None)
        if not imports_module:
            imports_module = {}
            self.imports[module_short] = imports_module

        key = (name, as_name)
        final_name = imports_module.get(key, None)

        if not final_name:
            # Cache miss, import the object
            final_name = as_name if as_name else name

            # If no as_name constraint was set, potentially adjust the
            # name to avoid conflicts with an existing object of the same name
            if not as_name and name and self.module:
                final_name = name
                while True:
                    # Accept the name if there are no conflicts
                    if not hasattr(self.module, final_name):
                        break
                    value = getattr(self.module, final_name)
                    try:
                        if module == ".":
                            mod_o = self.module
                        else:
                            mod_o = importlib.import_module(module)

                        # If there is a conflict, accept it if it refers to the same object
                        if getattr(mod_o, name) is value:
                            break
                    except ImportError:
                        pass

                    # Prefix with an underscore
                    final_name = "_" + final_name

            imports_module[key] = final_name

        return final_name

    def expr_str(self, e, abbrev=True):
        """Attempt to convert a value into a Python expression to generate that value"""
        tp = type(e)
        for t in [bool, int, type(None), type(...)]:
            if issubclass(tp, t):
                return repr(e)
        if issubclass(tp, float):
            s = repr(e)
            if "inf" in s or "nan" in s:
                return f"float('{s}')"
            else:
                return s
        elif self.is_enum(tp):
            return self.type_str(type(e)) + "." + e.__name__
        elif issubclass(tp, type):
            return self.type_str(e)
        elif issubclass(tp, typing.ForwardRef):
            return f'"{e.__forward_arg__}"'
        elif hasattr(typing, "TypeVarTuple") and \
             issubclass(tp, typing.TypeVarTuple):
            tv = self.import_object("typing", "TypeVarTuple")
            return f'{tv}("{e.__name__}")'
        elif issubclass(tp, typing.TypeVar):
            tv = self.import_object("typing", "TypeVar")
            s = f'{tv}("{e.__name__}"'
            for v in getattr(e, "__constraints__", ()):
                s += ", " + self.expr_str(v)
            for k in ["contravariant", "covariant", "bound", "infer_variance"]:
                v = getattr(e, f"__{k}__", None)
                if v:
                    v = self.expr_str(v)
                    if v is None:
                        return
                    s += f", {k}=" + v
            s += ")"
            return s
        elif issubclass(tp, str):
            s = repr(e)
            if len(s) < self.max_expr_length or not abbrev:
                return s
        elif issubclass(tp, list) or issubclass(tp, tuple):
            e = [self.expr_str(v, abbrev) for v in e]
            if None in e:
                return None
            if issubclass(tp, list):
                s = "[" + ", ".join(e) + "]"
            else:
                s = "(" + ", ".join(e) + ")"
            if len(s) < self.max_expr_length or not abbrev:
                return s
        elif issubclass(tp, dict):
            e = [
                (self.expr_str(k, abbrev), self.expr_str(v, abbrev))
                for k, v in e.items()
            ]
            s = "{"
            for i, (k, v) in enumerate(e):
                if k == None or v == None:
                    return None
                s += k + " : " + v
                if i + 1 < len(e):
                    s += ", "
            s += "}"
            if len(s) < self.max_expr_length or not abbrev:
                return s
            pass
        return None

    def signature_str(self, s: Signature):
        """Convert an inspect.Signature to into valid Python syntax"""
        posonly_sep, kwonly_sep = False, True
        params = []

        # Logic for placing '*' and '/' based on the
        # signature.Signature implementation
        for param in s.parameters.values():
            kind = param.kind

            if kind == Parameter.POSITIONAL_ONLY:
                posonly_sep = True
            elif posonly_sep:
                params.append('/')
                posonly_sep = False

            if kind == Parameter.VAR_POSITIONAL:
                kwonly_sep = False
            elif kind == Parameter.KEYWORD_ONLY and kwonly_sep:
                params.append('*')
                kwonly_sep = False
            params.append(self.param_str(param))

        if posonly_sep:
            params.append('/')

        result = f"({', '.join(params)})"
        if s.return_annotation != Signature.empty:
            result += " -> " + self.type_str(s.return_annotation)
        return result

    def param_str(self, p: Parameter):
        result = ''
        if p.kind == Parameter.VAR_POSITIONAL:
            result += '*'
        elif p.kind == Parameter.VAR_KEYWORD:
            result += '**'
        result += p.name
        has_type = p.annotation != Parameter.empty
        has_def  = p.default != Parameter.empty

        if has_type:
            result += ': ' + self.type_str(p.annotation)
        if has_def:
            result += ' = ' if has_type else '='
            result += self.expr_str(p.default)
        return result

    def type_str(self, tp):
        """Attempt to convert a type into a Python expression which reproduces it"""
        tp_tp = type(tp)
        generic_alias = 'GenericAlias' in tp_tp.__name__

        if isinstance(tp, typing.TypeVar):
            tp_name = tp.__name__
        elif isinstance(tp, type) and not generic_alias:
            tp_name = tp.__module__ + "." + tp.__qualname__
        else:
            tp_name = str(tp)
            if generic_alias or tp_tp.__module__ == 'typing':
                # Strip ~ and - from TypeVar names, which produces invalid Python code
                tp_name = re.sub(r'(?<=( |\[))[~-]', '', tp_name)
        return self.replace_standard_types(tp_name)

    def get(self):
        """Generate the final stub output"""
        s = ""

        for module in sorted(self.imports):
            imports = self.imports[module]
            items = []

            for (k, v1), v2 in imports.items():
                if k == None:
                    if v1 and v1 != module:
                        s += f"import {module} as {v1}\n"
                    else:
                        s += f"import {module}\n"
                else:
                    if k != v2 or v1:
                        items.append(f"{k} as {v2}")
                    else:
                        items.append(k)

            if items:
                items_v0 = ", ".join(items)
                items_v0 = f"from {module} import {items_v0}\n"
                items_v1 = "(\n    " + ",\n    ".join(items) + "\n)"
                items_v1 = f"from {module} import {items_v1}\n"
                s += items_v0 if len(items_v0) <= 70 else items_v1
        if s:
            s += "\n"
        s += self.put_abstract_enum_class()
        s += self.output
        return s.rstrip() + "\n"

    def put_abstract_enum_class(self):
        s = ""
        if not self.abstract_enum:
            return s

        s += f"class _Enum:\n"
        s += f"    def __init__(self, arg: object, /) -> None: ...\n"
        s += f"    def __repr__(self, /) -> str: ...\n"
        s += f"    def __hash__(self, /) -> int: ...\n"
        s += f"    def __int__(self, /) -> int: ...\n"
        s += f"    def __index__(self, /) -> int: ...\n"

        for op in ["eq", "ne"]:
            s += f"    def __{op}__(self, arg: object, /) -> bool: ...\n"

        for op in ["gt", "ge", "lt", "le"]:
            s += f"    def __{op}__(self, arg: object, /) -> bool: ...\n"
        s += f"    def name(self, /) -> str: ...\n"
        s += f"    def value(self, /) -> int: ...\n"
        s += "\n"

        if not self.abstract_enum_arith:
            return s

        s += f"class _EnumArith(_Enum):\n"
        for op in ["abs", "neg", "invert"]:
            s += f"    def __{op}__(self) -> int: ...\n"
        for op in [
            "add",
            "sub",
            "mul",
            "floordiv",
            "lshift",
            "rshift",
            "and",
            "or",
            "xor",
        ]:
            s += f"    def __{op}__(self, arg: object, /) -> int: ...\n"
            s += f"    def __r{op}__(self, arg: object, /) -> int: ...\n"

        s += "\n"
        return s


def parse_options(args):
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m nanobind.stubgen",
        description="Generate stubs for nanobind-based extensions.",
    )

    parser.add_argument(
        "-o",
        "--output-file",
        metavar="FILE",
        dest="output_file",
        default=None,
        help="write generated stubs to the specified file",
    )

    parser.add_argument(
        "-O",
        "--output-dir",
        metavar="PATH",
        dest="output_dir",
        default=None,
        help="write generated stubs to the specified directory",
    )

    parser.add_argument(
        "-i",
        "--import",
        action="append",
        metavar="PATH",
        dest="imports",
        default=[],
        help="add the directory to the Python import path (can specify multiple times)",
    )

    parser.add_argument(
        "-m",
        "--module",
        action="append",
        metavar="MODULE",
        dest="modules",
        default=[],
        help="generate a stub for the specified module (can specify multiple times)",
    )

    parser.add_argument(
        "-M",
        "--marker-file",
        metavar="FILE",
        dest="marker_file",
        default=None,
        help="generate a marker file (usually named 'py.typed')",
    )

    parser.add_argument(
        "-p",
        "--pattern-file",
        metavar="FILE",
        dest="pattern_file",
        default=None,
        help="apply the given patterns to the generated stub (see the docs for syntax)",
    )

    parser.add_argument(
        "-P",
        "--include-private",
        dest="include_private",
        default=False,
        action="store_true",
        help="include private members (with single leading or trailing underscore)",
    )

    parser.add_argument(
        "-D",
        "--exclude-docstrings",
        dest="include_docstrings",
        default=True,
        action="store_false",
        help="exclude docstrings from the generated stub",
    )

    parser.add_argument(
        "-q",
        "--quiet",
        default=False,
        action="store_true",
        help="do not generate any output in the absence of failures",
    )

    opt = parser.parse_args(args)
    if len(opt.modules) == 0:
        parser.error("At least one module must be specified.")
    if len(opt.modules) > 1 and opt.output_file:
        parser.error(
            "The -o option can only be specified when a single module is being processed."
        )
    return opt


def load_pattern_file(fname):
    with open(fname, "r") as f:
        lines = f.readlines()

    patterns = {}

    def add_pattern(query, pattern):
        # Exactly 1 empty line at the end
        while pattern and pattern[-1].isspace():
            pattern.pop()
        pattern.append("")

        # Identify deletions (replacement by only whitespace)
        if all((p.isspace() or len(p) == 0 for p in pattern)):
            pattern = []
        key = re.compile(query[:-1])
        if key in patterns:
            raise Exception(f'Duplicate query pattern "{query}"')
        patterns[key] = [pattern, 0]

    pattern, query, dedent = [], None, 0
    for i, l in enumerate(lines):
        l = l.rstrip()

        if l.startswith("#"):
            continue

        if len(l) == 0 or l[0].isspace():
            if not pattern:
                s = l.lstrip()
                dedent = len(l) - len(s)
                pattern.append(s)
            else:
                s1, s2 = l.lstrip(), l[dedent:]
                pattern.append(s2 if len(s2) > len(s1) else s1)

        else:
            if not l.endswith(":"):
                raise Exception(f'Cannot parse line {i+1} of pattern file "{fname}"')

            if query:
                add_pattern(query, pattern)
            query = l
            pattern = []

    if query:
        add_pattern(query, pattern)

    return patterns


def main(args=None):
    from pathlib import Path
    import sys
    import os

    # Ensure that the current directory is on the path
    if "" not in sys.path and "." not in sys.path:
        sys.path.insert(0, "")

    opt = parse_options(sys.argv[1:] if args is None else args)

    if opt.pattern_file:
        if not opt.quiet:
            print('Using pattern file "%s" ..' % opt.pattern_file)
        patterns = load_pattern_file(opt.pattern_file)
        if not opt.quiet:
            print("  - loaded %i patterns.\n" % len(patterns))
    else:
        patterns = {}

    for i in opt.imports:
        sys.path.insert(0, i)

    if opt.output_dir:
        os.makedirs(opt.output_dir, exist_ok=True)

    for i, mod in enumerate(opt.modules):
        if not opt.quiet:
            if i > 0:
                print("\n")
            print('Module "%s" ..' % mod)
            print("  - importing ..")
        mod_imported = importlib.import_module(mod)

        sg = StubGen(
            include_docstrings=opt.include_docstrings,
            include_private=opt.include_private,
            module=mod_imported,
            patterns=patterns,
        )

        if not opt.quiet:
            print("  - analyzing ..")

        sg.put(mod_imported)

        if opt.output_file:
            file = Path(opt.output_file)
        else:
            file = getattr(mod_imported, "__file__", None)
            if file is None:
                raise Exception(
                    'the module lacks a "__file__" attribute, hence '
                    "stubgen cannot infer where to place the generated "
                    "stub. You must specify the -o parameter to provide "
                    "the name of an output file."
                )
            file = Path(file)

            ext_loader = importlib.machinery.ExtensionFileLoader
            if isinstance(mod_imported.__loader__, ext_loader):
                file = file.with_name(mod_imported.__name__)
            file = file.with_suffix(".pyi")

            if opt.output_dir:
                file = Path(opt.output_dir, file.name)

        if patterns:
            matches = 0
            for k, v in patterns.items():
                if v[1] == 0:
                    rule_str = str(k)
                    if "re.compile" in rule_str:
                        rule_str = rule_str.replace("re.compile(", "")[:-1]
                    if not opt.quiet:
                        print(
                            f"  - warning: rule {rule_str} did not match any elements."
                        )
                matches += v[1]
            if not opt.quiet:
                print("  - applied %i patterns." % matches)

        if not opt.quiet:
            print('  - writing stub "%s" ..' % str(file))

        with open(file, "w") as f:
            f.write(sg.get())

    if opt.marker_file:
        if not opt.quiet:
            print('  - writing marker file "%s" ..' % opt.marker_file)
        Path(opt.marker_file).touch()


if __name__ == "__main__":
    main()
