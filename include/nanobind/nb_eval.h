/*
    nanobind/nb_eval.h: Support for evaluating Python expressions and
                        statements from strings

    Adapted by Nico Schlömer from pybind11's eval.h.

    All rights reserved. Use of this source code is governed by a
    BSD-style license that can be found in the LICENSE file.
*/

#pragma once

#include <nanobind/nanobind.h>

#include <utility>

NAMESPACE_BEGIN(NB_NAMESPACE)

enum eval_mode {
    // Evaluate a string containing an isolated expression
    eval_expr = Py_eval_input,

    // Evaluate a string containing a single statement. Returns \c none
    eval_single_statement = Py_single_input,

    // Evaluate a string containing a sequence of statement. Returns \c none
    eval_statements = Py_file_input
};

template <eval_mode start = eval_expr>
object eval(const str &expr, object global = object(), object local = object()) {
    if (!local)
        local = global;

    // This used to be PyRun_String, but that function isn't in the stable ABI.
    object codeobj = steal(Py_CompileString(expr.c_str(), "<string>", start));
    if (!codeobj)
        detail::raise_python_error();

    PyObject *result = PyEval_EvalCode(codeobj.ptr(), global.ptr(), local.ptr());
    if (!result)
        detail::raise_python_error();

    return steal(result);
}

template <eval_mode start = eval_expr, size_t N>
object eval(const char (&s)[N], object global = object(), object local = object()) {
    // Support raw string literals by removing common leading whitespace
    auto expr = (s[0] == '\n') ? str(module_::import_("textwrap").attr("dedent")(s)) : str(s);
    return eval<start>(expr, std::move(global), std::move(local));
}

inline void exec(const str &expr, object global = object(), object local = object()) {
    eval<eval_statements>(expr, std::move(global), std::move(local));
}

template <size_t N>
void exec(const char (&s)[N], object global = object(), object local = object()) {
    eval<eval_statements>(s, std::move(global), std::move(local));
}

NAMESPACE_END(NB_NAMESPACE)
