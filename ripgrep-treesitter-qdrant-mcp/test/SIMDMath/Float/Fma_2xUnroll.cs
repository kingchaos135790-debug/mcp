using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Runtime.Intrinsics;
using System.Runtime.Intrinsics.X86;
using System.Diagnostics;
using System.Threading.Tasks;

namespace MyProject
{
    public static partial class SIMDMath
    {
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void AllFma(this Span<float> left, float multiplicand, float addend)
        {
            s_fpOps.Fma_2xUnroll(left, multiplicand, addend);
        }
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void AllFma(this Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend)
        {
            if (left.Length != multiplicand.Length || left.Length != addend.Length) throw new ArgumentException("Length mismatch");
            s_fpOps.Fma_2xUnroll(left, multiplicand, addend);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void AllFma(this Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend, Span<float> result)
        {
            if (left.Length != multiplicand.Length || left.Length != addend.Length || left.Length != result.Length) throw new ArgumentException("Length mismatch");
            s_fpOps.Fma_2xUnroll(left, multiplicand, addend, result);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void AllFma(this Span<float> left, float multiplicand, float addend, Span<float> result)
        {
            if (left.Length != result.Length) throw new ArgumentException("Length mismatch");
            s_fpOps.Fma_2xUnroll(left, multiplicand, addend, result);
        }

        // =============================
        // Fused Multiply-Add (binary + const forms)
        // left = left * multiplicand + addend
        // =============================
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatAvx2_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend)
        {
            int len = left.Length;
            int width = Vector256<float>.Count; int unroll = width * 2;
#if DEBUG
            Debug.Assert(len >= 0, "Length must be non-negative");
            Debug.Assert(left.Length == multiplicand.Length && left.Length == addend.Length, "Spans must have the same length.");
            Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
            fixed (float* pLeft = left)
            fixed (float* pMul = multiplicand)
            fixed (float* pAdd = addend)
            {
#if DEBUG
                // ALIAS CHECK: ensure spans do not overlap
                var leftAddr = (UIntPtr)pLeft;
                var mulAddr = (UIntPtr)pMul;
                var addAddr = (UIntPtr)pAdd;
                var byteLength = (UIntPtr)(len * sizeof(float));
                bool overlapLM = leftAddr < mulAddr + byteLength && mulAddr < leftAddr + byteLength;
                bool overlapLA = leftAddr < addAddr + byteLength && addAddr < leftAddr + byteLength;
                Debug.Assert(!overlapLM && !overlapLA, "Input spans must not overlap (alias) for SIMD FMA path.");
#endif
                if (Fma.IsSupported)
                {
                    for (int i = 0; i < len; i += unroll)
                    {
                        var l0 = Avx.LoadVector256(pLeft + i);
                        var m0 = Avx.LoadVector256(pMul + i);
                        var a0 = Avx.LoadVector256(pAdd + i);
                        var l1 = Avx.LoadVector256(pLeft + i + width);
                        var m1 = Avx.LoadVector256(pMul + i + width);
                        var a1 = Avx.LoadVector256(pAdd + i + width);
                        l0 = Fma.MultiplyAdd(l0, m0, a0);
                        l1 = Fma.MultiplyAdd(l1, m1, a1);
                        Avx.Store(pLeft + i, l0);
                        Avx.Store(pLeft + i + width, l1);
                    }
                }
                else
                {
                    // Fallback for CPUs with AVX but not FMA
                    for (int i = 0; i < len; i += unroll)
                    {
                        var l0 = Avx.LoadVector256(pLeft + i);
                        var m0 = Avx.LoadVector256(pMul + i);
                        var a0 = Avx.LoadVector256(pAdd + i);
                        var l1 = Avx.LoadVector256(pLeft + i + width);
                        var m1 = Avx.LoadVector256(pMul + i + width);
                        var a1 = Avx.LoadVector256(pAdd + i + width);
                        l0 = Avx.Add(Avx.Multiply(l0, m0), a0); // Separate multiply and add
                        l1 = Avx.Add(Avx.Multiply(l1, m1), a1);
                        Avx.Store(pLeft + i, l0);
                        Avx.Store(pLeft + i + width, l1);
                    }
                }
            }
        }
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void FmaFloatAvx_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend)
        {
            // Same as Avx2 path (no int ops) - reuse implementation
            FmaFloatAvx2_2xUnroll(left, multiplicand, addend);
        }
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatSse41_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend)
        {
            int len = left.Length;
            int width = Vector128<float>.Count; int unroll = width * 2;
#if DEBUG
            Debug.Assert(len >= 0, "Length must be non-negative");
            Debug.Assert(left.Length == multiplicand.Length && left.Length == addend.Length, "Spans must have the same length.");
            Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
            fixed (float* pLeft = left)
            fixed (float* pMul = multiplicand)
            fixed (float* pAdd = addend)
            {
#if DEBUG
                // ALIAS CHECK: ensure spans do not overlap
                var leftAddr = (UIntPtr)pLeft;
                var mulAddr = (UIntPtr)pMul;
                var addAddr = (UIntPtr)pAdd;
                var byteLength = (UIntPtr)(len * sizeof(float));
                bool overlapLM = leftAddr < mulAddr + byteLength && mulAddr < leftAddr + byteLength;
                bool overlapLA = leftAddr < addAddr + byteLength && addAddr < leftAddr + byteLength;
                Debug.Assert(!overlapLM && !overlapLA, "Input spans must not overlap (alias) for SIMD FMA path.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var l0 = Sse.LoadVector128(pLeft + i);
                    var m0 = Sse.LoadVector128(pMul + i);
                    var a0 = Sse.LoadVector128(pAdd + i);
                    var l1 = Sse.LoadVector128(pLeft + i + width);
                    var m1 = Sse.LoadVector128(pMul + i + width);
                    var a1 = Sse.LoadVector128(pAdd + i + width);
                    l0 = Sse.Add(Sse.Multiply(l0, m0), a0);
                    l1 = Sse.Add(Sse.Multiply(l1, m1), a1);
                    Sse.Store(pLeft + i, l0);
                    Sse.Store(pLeft + i + width, l1);
                }
                // No scalar remainder handling: caller must provide lengths that are
                // a non-zero multiple of the SIMD unroll (see Debug.Assert above).
            }
        }
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatSse2_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend) => FmaFloatSse41_2xUnroll(left, multiplicand, addend);
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static void FmaFloatScalar_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend)
    { int len = left.Length; for (int i = 0; i < len; i++) left[i] = left[i] * multiplicand[i] + addend[i]; }

        // Constant FMA: left = left * multiplicand + addend with scalar multiplicand & addend
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatAvx2Const_2xUnroll(Span<float> left, float multiplicand, float addend)
        {
            int len = left.Length;
            int width = Vector256<float>.Count; int unroll = width * 2;
            var mulV = Vector256.Create(multiplicand);
            var addV = Vector256.Create(addend);
            fixed (float* pLeft = left)
            {
#if DEBUG
                Debug.Assert(len >= 0, "Length must be non-negative");
                Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
                if (System.Runtime.Intrinsics.X86.Fma.IsSupported)
                {
                    for (int i = 0; i < len; i += unroll)
                    {
                        var l0 = Avx.LoadVector256(pLeft + i);
                        var l1 = Avx.LoadVector256(pLeft + i + width);
                        l0 = System.Runtime.Intrinsics.X86.Fma.MultiplyAdd(l0, mulV, addV);
                        l1 = System.Runtime.Intrinsics.X86.Fma.MultiplyAdd(l1, mulV, addV);
                        Avx.Store(pLeft + i, l0);
                        Avx.Store(pLeft + i + width, l1);
                    }
                }
                else
                {
                    // AVX fallback when FMA not present: multiply then add vectorized.
                    for (int i = 0; i < len; i += unroll)
                    {
                        var l0 = Avx.LoadVector256(pLeft + i);
                        var l1 = Avx.LoadVector256(pLeft + i + width);
                        l0 = Avx.Add(Avx.Multiply(l0, mulV), addV);
                        l1 = Avx.Add(Avx.Multiply(l1, mulV), addV);
                        Avx.Store(pLeft + i, l0);
                        Avx.Store(pLeft + i + width, l1);
                    }
                }
                // No scalar remainder handling: caller must ensure length matches vector block size.
            }
        }
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatAvxConst_2xUnroll(Span<float> left, float multiplicand, float addend) => FmaFloatAvx2Const_2xUnroll(left, multiplicand, addend);
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatSse41Const_2xUnroll(Span<float> left, float multiplicand, float addend)
        {
            int len = left.Length; int width = Vector128<float>.Count; int unroll = width * 2; var mulV = Vector128.Create(multiplicand); var addV = Vector128.Create(addend);
            fixed (float* pLeft = left)
            {
#if DEBUG
                Debug.Assert(len % (Vector128<float>.Count * 2) == 0 && len != 0, $"Span length must be a non-zero multiple of {Vector128<float>.Count * 2} for this optimized method.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var l0 = Sse.LoadVector128(pLeft + i);
                    var l1 = Sse.LoadVector128(pLeft + i + width);
                    l0 = Sse.Add(Sse.Multiply(l0, mulV), addV);
                    l1 = Sse.Add(Sse.Multiply(l1, mulV), addV);
                    Sse.Store(pLeft + i, l0);
                    Sse.Store(pLeft + i + width, l1);
                }
                // No scalar remainder handling: caller must ensure length matches vector block size.
            }
        }
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatSse2Const_2xUnroll(Span<float> left, float multiplicand, float addend) => FmaFloatSse41Const_2xUnroll(left, multiplicand, addend);
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static void FmaFloatScalarConst_2xUnroll(Span<float> left, float multiplicand, float addend)
    { int len = left.Length; for (int i = 0; i < len; i++) left[i] = left[i] * multiplicand + addend; }


        // =============================
        // Fused Multiply-Add (binary) with result span
        // =============================
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatAvx2_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend, Span<float> result)
        {
            int len = left.Length;
            int width = Vector256<float>.Count; int unroll = width * 2;
#if DEBUG
            Debug.Assert(len >= 0, "Length must be non-negative");
            Debug.Assert(left.Length == multiplicand.Length && left.Length == addend.Length && left.Length == result.Length, "Spans must have the same length.");
            Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
            fixed (float* pLeft = left)
            fixed (float* pMul = multiplicand)
            fixed (float* pAdd = addend)
            fixed (float* pResult = result)
            {
#if DEBUG
                // ALIAS CHECK
                var leftAddr = (UIntPtr)pLeft;
                var mulAddr = (UIntPtr)pMul;
                var addAddr = (UIntPtr)pAdd;
                var resultAddr = (UIntPtr)pResult;
                var byteLength = (UIntPtr)(left.Length * sizeof(float));
                bool overlapRL = resultAddr < leftAddr + byteLength && leftAddr < resultAddr + byteLength;
                bool overlapRM = resultAddr < mulAddr + byteLength && mulAddr < resultAddr + byteLength;
                bool overlapRA = resultAddr < addAddr + byteLength && addAddr < resultAddr + byteLength;
                Debug.Assert(!overlapRL && !overlapRM && !overlapRA, "Result span must not overlap with input spans.");
#endif
                if (Fma.IsSupported)
                {
                    for (int i = 0; i < len; i += unroll)
                    {
                        var l0 = Avx.LoadVector256(pLeft + i);
                        var m0 = Avx.LoadVector256(pMul + i);
                        var a0 = Avx.LoadVector256(pAdd + i);
                        var l1 = Avx.LoadVector256(pLeft + i + width);
                        var m1 = Avx.LoadVector256(pMul + i + width);
                        var a1 = Avx.LoadVector256(pAdd + i + width);
                        var res0 = Fma.MultiplyAdd(l0, m0, a0);
                        var res1 = Fma.MultiplyAdd(l1, m1, a1);
                        Avx.Store(pResult + i, res0);
                        Avx.Store(pResult + i + width, res1);
                    }
                }
                else
                {
                    for (int i = 0; i < len; i += unroll)
                    {
                        var l0 = Avx.LoadVector256(pLeft + i);
                        var m0 = Avx.LoadVector256(pMul + i);
                        var a0 = Avx.LoadVector256(pAdd + i);
                        var l1 = Avx.LoadVector256(pLeft + i + width);
                        var m1 = Avx.LoadVector256(pMul + i + width);
                        var a1 = Avx.LoadVector256(pAdd + i + width);
                        var res0 = Avx.Add(Avx.Multiply(l0, m0), a0);
                        var res1 = Avx.Add(Avx.Multiply(l1, m1), a1);
                        Avx.Store(pResult + i, res0);
                        Avx.Store(pResult + i + width, res1);
                    }
                }
            }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatAvx_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend, Span<float> result) => FmaFloatAvx2_2xUnroll(left, multiplicand, addend, result);

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatSse41_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend, Span<float> result)
        {
            int len = left.Length;
            int width = Vector128<float>.Count; int unroll = width * 2;
#if DEBUG
            Debug.Assert(len >= 0, "Length must be non-negative");
            Debug.Assert(left.Length == multiplicand.Length && left.Length == addend.Length && left.Length == result.Length, "Spans must have the same length.");
            Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
            fixed (float* pLeft = left)
            fixed (float* pMul = multiplicand)
            fixed (float* pAdd = addend)
            fixed (float* pResult = result)
            {
#if DEBUG
                // ALIAS CHECK
                var leftAddr = (UIntPtr)pLeft;
                var mulAddr = (UIntPtr)pMul;
                var addAddr = (UIntPtr)pAdd;
                var resultAddr = (UIntPtr)pResult;
                var byteLength = (UIntPtr)(left.Length * sizeof(float));
                bool overlapRL = resultAddr < leftAddr + byteLength && leftAddr < resultAddr + byteLength;
                bool overlapRM = resultAddr < mulAddr + byteLength && mulAddr < resultAddr + byteLength;
                bool overlapRA = resultAddr < addAddr + byteLength && addAddr < resultAddr + byteLength;
                Debug.Assert(!overlapRL && !overlapRM && !overlapRA, "Result span must not overlap with input spans.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var l0 = Sse.LoadVector128(pLeft + i);
                    var m0 = Sse.LoadVector128(pMul + i);
                    var a0 = Sse.LoadVector128(pAdd + i);
                    var l1 = Sse.LoadVector128(pLeft + i + width);
                    var m1 = Sse.LoadVector128(pMul + i + width);
                    var a1 = Sse.LoadVector128(pAdd + i + width);
                    var res0 = Sse.Add(Sse.Multiply(l0, m0), a0);
                    var res1 = Sse.Add(Sse.Multiply(l1, m1), a1);
                    Sse.Store(pResult + i, res0);
                    Sse.Store(pResult + i + width, res1);
                }
            }
        }
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatSse2_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend, Span<float> result) => FmaFloatSse41_2xUnroll(left, multiplicand, addend, result);
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static void FmaFloatScalar_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend, Span<float> result)
    { for (int i = 0; i < left.Length; i++) result[i] = left[i] * multiplicand[i] + addend[i]; }

        // =============================
        // Fused Multiply-Add (constant) with result span
        // =============================
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatAvx2Const_2xUnroll(ReadOnlySpan<float> left, float multiplicand, float addend, Span<float> result)
        {
            int len = left.Length;
            int width = Vector256<float>.Count; int unroll = width * 2;
            var mulV = Vector256.Create(multiplicand);
            var addV = Vector256.Create(addend);
#if DEBUG
            Debug.Assert(len >= 0, "Length must be non-negative");
            Debug.Assert(left.Length == result.Length, "Spans must have the same length.");
            Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
            fixed (float* pLeft = left)
            fixed (float* pResult = result)
            {
#if DEBUG
                // ALIAS CHECK
                var leftAddr = (UIntPtr)pLeft;
                var resultAddr = (UIntPtr)pResult;
                var byteLength = (UIntPtr)(left.Length * sizeof(float));
                bool overlapRL = resultAddr < leftAddr + byteLength && leftAddr < resultAddr + byteLength;
                Debug.Assert(!overlapRL, "Result span must not overlap with input span.");
#endif
                if (Fma.IsSupported)
                {
                    for (int i = 0; i < len; i += unroll)
                    {
                        var l0 = Avx.LoadVector256(pLeft + i);
                        var l1 = Avx.LoadVector256(pLeft + i + width);
                        var res0 = Fma.MultiplyAdd(l0, mulV, addV);
                        var res1 = Fma.MultiplyAdd(l1, mulV, addV);
                        Avx.Store(pResult + i, res0);
                        Avx.Store(pResult + i + width, res1);
                    }
                }
                else
                {
                    for (int i = 0; i < len; i += unroll)
                    {
                        var l0 = Avx.LoadVector256(pLeft + i);
                        var l1 = Avx.LoadVector256(pLeft + i + width);
                        var res0 = Avx.Add(Avx.Multiply(l0, mulV), addV);
                        var res1 = Avx.Add(Avx.Multiply(l1, mulV), addV);
                        Avx.Store(pResult + i, res0);
                        Avx.Store(pResult + i + width, res1);
                    }
                }
            }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatAvxConst_2xUnroll(ReadOnlySpan<float> left, float multiplicand, float addend, Span<float> result) => FmaFloatAvx2Const_2xUnroll(left, multiplicand, addend, result);

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatSse41Const_2xUnroll(ReadOnlySpan<float> left, float multiplicand, float addend, Span<float> result)
        {
            int len = left.Length; int width = Vector128<float>.Count; int unroll = width * 2;
            var mulV = Vector128.Create(multiplicand);
            var addV = Vector128.Create(addend);
#if DEBUG
            Debug.Assert(len >= 0, "Length must be non-negative");
            Debug.Assert(left.Length == result.Length, "Spans must have the same length.");
            Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
            fixed (float* pLeft = left)
            fixed (float* pResult = result)
            {
#if DEBUG
                // ALIAS CHECK
                var leftAddr = (UIntPtr)pLeft;
                var resultAddr = (UIntPtr)pResult;
                var byteLength = (UIntPtr)(left.Length * sizeof(float));
                bool overlapRL = resultAddr < leftAddr + byteLength && leftAddr < resultAddr + byteLength;
                Debug.Assert(!overlapRL, "Result span must not overlap with input span.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var l0 = Sse.LoadVector128(pLeft + i);
                    var l1 = Sse.LoadVector128(pLeft + i + width);
                    var res0 = Sse.Add(Sse.Multiply(l0, mulV), addV);
                    var res1 = Sse.Add(Sse.Multiply(l1, mulV), addV);
                    Sse.Store(pResult + i, res0);
                    Sse.Store(pResult + i + width, res1);
                }
            }
        }
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void FmaFloatSse2Const_2xUnroll(ReadOnlySpan<float> left, float multiplicand, float addend, Span<float> result) => FmaFloatSse41Const_2xUnroll(left, multiplicand, addend, result);
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static void FmaFloatScalarConst_2xUnroll(ReadOnlySpan<float> left, float multiplicand, float addend, Span<float> result)
    { for (int i = 0; i < left.Length; i++) result[i] = left[i] * multiplicand + addend; }
    }
}