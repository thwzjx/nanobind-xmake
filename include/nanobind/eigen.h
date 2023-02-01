/*
    nanobind/eigen.h: type casters for the Eigen library

    The type casters in this header file can pass dense Eigen
    vectors and matrices

    Copyright (c) 2023 Wenzel Jakob

    All rights reserved. Use of this source code is governed by a
    BSD-style license that can be found in the LICENSE file.
*/

#pragma once

#include <nanobind/tensor.h>
#include <Eigen/Core>

static_assert(EIGEN_VERSION_AT_LEAST(3, 2, 7),
              "Eigen matrix support in pybind11 requires Eigen >= 3.2.7");

NAMESPACE_BEGIN(NB_NAMESPACE)
NAMESPACE_BEGIN(detail)

template <typename T>
using tensor_for_eigen_t = tensor<
    typename T::Scalar,
    numpy,
    std::conditional_t<
        T::NumDimensions == 1,
        shape<(size_t) T::SizeAtCompileTime>,
        shape<(size_t) T::RowsAtCompileTime,
              (size_t) T::ColsAtCompileTime>>,
    std::conditional_t<
        T::IsRowMajor || T::NumDimensions == 1,
        c_contig, f_contig>
>;

/// Any kind of Eigen class
template <typename T> constexpr bool is_eigen_v =
is_base_of_template_v<T, Eigen::EigenBase>;

/// Detects Eigen::Array, Eigen::Matrix, etc.
template <typename T> constexpr bool is_eigen_plain_v =
is_base_of_template_v<T, Eigen::PlainObjectBase>;

/// Detects expression templates
template <typename T> constexpr bool is_eigen_xpr_v =
    is_eigen_v<T> && !is_eigen_plain_v<T> &&
    !std::is_base_of_v<Eigen::MapBase<T, Eigen::ReadOnlyAccessors>, T>;

template <typename T> struct type_caster<T, enable_if_t<is_eigen_plain_v<T>>> {
    using Scalar = typename T::Scalar;
    using Tensor = tensor_for_eigen_t<T>;
    using TensorCaster = make_caster<Tensor>;

    NB_TYPE_CASTER(T, TensorCaster::Name);

    bool from_python(handle src, uint8_t flags, cleanup_list *cleanup) noexcept {
        TensorCaster caster;
        if (!caster.from_python(src, flags, cleanup))
            return false;
        const Tensor &tensor = caster.value;

        if constexpr (T::NumDimensions == 1) {
            value.resize(tensor.shape(0));
            memcpy(value.data(), tensor.data(),
                   tensor.shape(0) * sizeof(Scalar));
        } else {
            value.resize(tensor.shape(0), tensor.shape(1));
            memcpy(value.data(), tensor.data(),
                   tensor.shape(0) * tensor.shape(1) * sizeof(Scalar));
        }

        return true;
    }

    static handle from_cpp(T &&v, rv_policy policy, cleanup_list *cleanup) noexcept {
        if (policy == rv_policy::automatic ||
            policy == rv_policy::automatic_reference)
            policy = rv_policy::move;

        return from_cpp((const T &) v, policy, cleanup);
    }

    static handle from_cpp(const T &v, rv_policy policy, cleanup_list *cleanup) noexcept {
        size_t shape[T::NumDimensions];
        int64_t strides[T::NumDimensions];

        if constexpr (T::NumDimensions == 1) {
            shape[0] = v.size();
            strides[0] = v.innerStride();
        } else {
            shape[0] = v.rows();
            shape[1] = v.cols();
            strides[0] = v.rowStride();
            strides[1] = v.colStride();
        }

        void *ptr = (void *) v.data();

        switch (policy) {
            case rv_policy::automatic:
                policy = rv_policy::copy;
                break;

            case rv_policy::automatic_reference:
                policy = rv_policy::reference;
                break;

            case rv_policy::move:
                // Don't bother moving when the data is static or occupies <1KB
                if ((T::SizeAtCompileTime != Eigen::Dynamic ||
                     (size_t) v.size() < (1024 / sizeof(Scalar))))
                    policy = rv_policy::copy;
                break;

            default: // leave policy unchanged
                break;
        }

        object owner;
        if (policy == rv_policy::move) {
            T *temp = new T(std::move(v));
            owner = capsule(temp, [](void *p) noexcept { delete (T *) p; });
            ptr = temp->data();
        }

        rv_policy tensor_rv_policy =
            policy == rv_policy::move ? rv_policy::reference : policy;

        object o = steal(TensorCaster::from_cpp(
            Tensor(ptr, T::NumDimensions, shape, owner, strides),
            tensor_rv_policy, cleanup));

        return o.release();
    }
};

/// Caster for Eigen expression templates
template <typename T> struct type_caster<T, enable_if_t<is_eigen_xpr_v<T>>> {
    using Array = Eigen::Array<typename T::Scalar, T::RowsAtCompileTime,
                               T::ColsAtCompileTime>;
    using Caster = make_caster<Array>;
    static constexpr auto Name = Caster::Name;
    template <typename T_> using Cast = T;

    /// Generating an expression template from a Python object is, of course, not possible
    bool from_python(handle src, uint8_t flags, cleanup_list *cleanup) noexcept = delete;

    template <typename T2>
    static handle from_cpp(T2 &&v, rv_policy policy, cleanup_list *cleanup) noexcept {
        return Caster::from_cpp(std::forward<T2>(v), policy, cleanup);
    }
};

/// Caster for Eigen::Map<T>
template <typename T, int MapOptions, typename StrideType>
struct type_caster<Eigen::Map<T, MapOptions, StrideType>> {
    using Map = Eigen::Map<T, MapOptions, StrideType>;
    using Tensor = tensor_for_eigen_t<Map>;
    using TensorCaster = type_caster<Tensor>;
    static constexpr auto Name = TensorCaster::Name;
    template <typename T_> using Cast = Map;

    TensorCaster caster;

    bool from_python(handle src, uint8_t flags,
                     cleanup_list *cleanup) noexcept {
        return caster.from_python(src, flags, cleanup);
    }

    static handle from_cpp(const Map &v, rv_policy, cleanup_list *cleanup) noexcept {
        size_t shape[T::NumDimensions];
        int64_t strides[T::NumDimensions];

        if constexpr (T::NumDimensions == 1) {
            shape[0] = v.size();
            strides[0] = v.innerStride();
        } else {
            shape[0] = v.rows();
            shape[1] = v.cols();
            strides[0] = v.rowStride();
            strides[1] = v.colStride();
        }

        return TensorCaster::from_cpp(
            Tensor((void *) v.data(), T::NumDimensions, shape, handle(), strides),
            rv_policy::reference, cleanup);
    }

    operator Map() {
        Tensor &t = caster.value;
        return Map(t.data(), t.shape(0), t.shape(1));
    }
};

/// Caster for Eigen::Ref<T>
template <typename T> struct type_caster<Eigen::Ref<T>> {
    using Ref = Eigen::Ref<T>;
    using Map = Eigen::Map<T>;
    using MapCaster = make_caster<Map>;
    static constexpr auto Name = MapCaster::Name;
    template <typename T_> using Cast = Ref;

    MapCaster caster;

    bool from_python(handle src, uint8_t flags,
                     cleanup_list *cleanup) noexcept {
        return caster.from_python(src, flags, cleanup);
    }

    operator Ref() { return Ref(caster.operator Map()); }
};

NAMESPACE_END(detail)
NAMESPACE_END(NB_NAMESPACE)
