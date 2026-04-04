using System;
using System.Runtime.Intrinsics;
using System.Runtime.Intrinsics.X86;
using System.Runtime.InteropServices;
using System.Runtime.CompilerServices;
using System.Diagnostics; // Added for Debug.Assert
using Arch.LowLevel;

namespace MyProject
{
    public static partial class SIMDMath
    {
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void Mul(this Span<float> left, ReadOnlySpan<float> right)
        {
            if (left.Length != right.Length) throw new ArgumentException("Length mismatch");
            s_fpOps.Mul_2xUnroll(left, right);
        }
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void Mul(this Span<float> left, float value)
        {
            s_fpOps.Mul_2xUnroll(left, value);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void lMul(this Span<float> left, ReadOnlySpan<float> right, Span<float> result)
        {
            if (left.Length != right.Length || left.Length != result.Length) throw new ArgumentException("Length mismatch");
            s_fpOps.Mul_2xUnroll(left, right, result);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void Mul(this Span<float> left, float value, Span<float> result)
        {
            if (left.Length != result.Length) throw new ArgumentException("Length mismatch");
            s_fpOps.Mul_2xUnroll(left, value, result);
        }

        // =============================
        // Multiplication (binary)
        // =============================

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void MulFloatAvx2_2xUnroll(Span<float> left, ReadOnlySpan<float> right)
        {
            int len = left.Length;
            int width = Vector256<float>.Count;
            int unroll = width * 2;
#if DEBUG
            Debug.Assert(len >= 0, "Length must be non-negative");
            Debug.Assert(left.Length == right.Length, "Spans must have the same length.");
            Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
            fixed (float* pLeft = left)
            fixed (float* pRight = right)
            {
#if DEBUG
                // ALIAS CHECK: ensure spans do not overlap
                var leftAddr = (UIntPtr)pLeft;
                var rightAddr = (UIntPtr)pRight;
                var byteLength = (UIntPtr)(len * sizeof(float));
                bool overlap = leftAddr < rightAddr + byteLength && rightAddr < leftAddr + byteLength;
                Debug.Assert(!overlap, "Input spans must not overlap (alias) for this SIMD path.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var a0 = Avx.LoadVector256(pLeft + i);
                    var b0 = Avx.LoadVector256(pRight + i);
                    var a1 = Avx.LoadVector256(pLeft + i + width);
                    var b1 = Avx.LoadVector256(pRight + i + width);
                    a0 = Avx.Multiply(a0, b0);
                    a1 = Avx.Multiply(a1, b1);
                    Avx.Store(pLeft + i, a0);
                    Avx.Store(pLeft + i + width, a1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatAvx_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => MulFloatAvx2_2xUnroll(left, right);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatSse41_2xUnroll(Span<float> left, ReadOnlySpan<float> right)
        {
            int len = left.Length;
            int width = Vector128<float>.Count;
            int unroll = width * 2;
#if DEBUG
            Debug.Assert(len >= 0, "Length must be non-negative");
            Debug.Assert(left.Length == right.Length, "Spans must have the same length.");
            Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
            fixed (float* pLeft = left)
            fixed (float* pRight = right)
            {
#if DEBUG
                // ALIAS CHECK: ensure spans do not overlap
                var leftAddr = (UIntPtr)pLeft;
                var rightAddr = (UIntPtr)pRight;
                var byteLength = (UIntPtr)(len * sizeof(float));
                bool overlap = leftAddr < rightAddr + byteLength && rightAddr < leftAddr + byteLength;
                Debug.Assert(!overlap, "Input spans must not overlap (alias) for this SIMD path.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var a0 = Sse.LoadVector128(pLeft + i);
                    var b0 = Sse.LoadVector128(pRight + i);
                    var a1 = Sse.LoadVector128(pLeft + i + width);
                    var b1 = Sse.LoadVector128(pRight + i + width);
                    a0 = Sse.Multiply(a0, b0);
                    a1 = Sse.Multiply(a1, b1);
                    Sse.Store(pLeft + i, a0);
                    Sse.Store(pLeft + i + width, a1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatSse2_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => MulFloatSse41_2xUnroll(left, right);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static void MulFloatScalar_2xUnroll(Span<float> left, ReadOnlySpan<float> right)
        {
            for (int i = 0; i < left.Length; i++)
                left[i] *= right[i];
        }

        // =============================
        // Multiplication (constant)
        // =============================

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatAvx2Const_2xUnroll(Span<float> left, float value)
        {
            int len = left.Length;
            int width = Vector256<float>.Count;
            int unroll = width * 2;
            var mul = Vector256.Create(value);
            fixed (float* pLeft = left)
            {
#if DEBUG
                Debug.Assert(len >= 0, "Length must be non-negative");
                Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var a0 = Avx.LoadVector256(pLeft + i);
                    var a1 = Avx.LoadVector256(pLeft + i + width);
                    a0 = Avx.Multiply(a0, mul);
                    a1 = Avx.Multiply(a1, mul);
                    Avx.Store(pLeft + i, a0);
                    Avx.Store(pLeft + i + width, a1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatAvxConst_2xUnroll(Span<float> left, float value) => MulFloatAvx2Const_2xUnroll(left, value);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatSse41Const_2xUnroll(Span<float> left, float value)
        {
            int len = left.Length;
            int width = Vector128<float>.Count;
            int unroll = width * 2;
            var mul = Vector128.Create(value);
            fixed (float* pLeft = left)
            {
#if DEBUG
                Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var a0 = Sse.LoadVector128(pLeft + i);
                    var a1 = Sse.LoadVector128(pLeft + i + width);
                    a0 = Sse.Multiply(a0, mul);
                    a1 = Sse.Multiply(a1, mul);
                    Sse.Store(pLeft + i, a0);
                    Sse.Store(pLeft + i + width, a1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatSse2Const_2xUnroll(Span<float> left, float value) => MulFloatSse41Const_2xUnroll(left, value);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static void MulFloatScalarConst_2xUnroll(Span<float> left, float value)
        {
            for (int i = 0; i < left.Length; i++)
                left[i] *= value;
        }

        // =============================
        // Multiplication (binary) with result span
        // =============================

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatAvx2_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> right, Span<float> result)
        {
            int len = left.Length;
            int width = Vector256<float>.Count;
            int unroll = width * 2;
#if DEBUG
            Debug.Assert(len >= 0, "Length must be non-negative");
            Debug.Assert(left.Length == right.Length && left.Length == result.Length, "Spans must have the same length.");
            Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
            fixed (float* pLeft = left)
            fixed (float* pRight = right)
            fixed (float* pResult = result)
            {
#if DEBUG
                // ALIAS CHECK
                var leftAddr = (UIntPtr)pLeft;
                var rightAddr = (UIntPtr)pRight;
                var resultAddr = (UIntPtr)pResult;
                var byteLength = (UIntPtr)(left.Length * sizeof(float));
                bool overlapRL = resultAddr < leftAddr + byteLength && leftAddr < resultAddr + byteLength;
                bool overlapRR = resultAddr < rightAddr + byteLength && rightAddr < resultAddr + byteLength;
                Debug.Assert(!overlapRL && !overlapRR, "Result span must not overlap with input spans.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var a0 = Avx.LoadVector256(pLeft + i);
                    var b0 = Avx.LoadVector256(pRight + i);
                    var a1 = Avx.LoadVector256(pLeft + i + width);
                    var b1 = Avx.LoadVector256(pRight + i + width);
                    var res0 = Avx.Multiply(a0, b0);
                    var res1 = Avx.Multiply(a1, b1);
                    Avx.Store(pResult + i, res0);
                    Avx.Store(pResult + i + width, res1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatAvx_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> right, Span<float> result) => MulFloatAvx2_2xUnroll(left, right, result);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatSse41_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> right, Span<float> result)
        {
            int len = left.Length;
            int width = Vector128<float>.Count;
            int unroll = width * 2;
#if DEBUG
            Debug.Assert(len >= 0, "Length must be non-negative");
            Debug.Assert(left.Length == right.Length && left.Length == result.Length, "Spans must have the same length.");
            Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
            fixed (float* pLeft = left)
            fixed (float* pRight = right)
            fixed (float* pResult = result)
            {
#if DEBUG
                // ALIAS CHECK
                var leftAddr = (UIntPtr)pLeft;
                var rightAddr = (UIntPtr)pRight;
                var resultAddr = (UIntPtr)pResult;
                var byteLength = (UIntPtr)(left.Length * sizeof(float));
                bool overlapRL = resultAddr < leftAddr + byteLength && leftAddr < resultAddr + byteLength;
                bool overlapRR = resultAddr < rightAddr + byteLength && rightAddr < resultAddr + byteLength;
                Debug.Assert(!overlapRL && !overlapRR, "Result span must not overlap with input spans.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var a0 = Sse.LoadVector128(pLeft + i);
                    var b0 = Sse.LoadVector128(pRight + i);
                    var a1 = Sse.LoadVector128(pLeft + i + width);
                    var b1 = Sse.LoadVector128(pRight + i + width);
                    var res0 = Sse.Multiply(a0, b0);
                    var res1 = Sse.Multiply(a1, b1);
                    Sse.Store(pResult + i, res0);
                    Sse.Store(pResult + i + width, res1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatSse2_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> right, Span<float> result) => MulFloatSse41_2xUnroll(left, right, result);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static void MulFloatScalar_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> right, Span<float> result)
        {
            for (int i = 0; i < left.Length; i++)
                result[i] = left[i] * right[i];
        }

        // =============================
        // Multiplication (constant) with result span
        // =============================

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatAvx2Const_2xUnroll(ReadOnlySpan<float> left, float value, Span<float> result)
        {
            int len = left.Length;
            int width = Vector256<float>.Count;
            int unroll = width * 2;
            var mul = Vector256.Create(value);
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
                    var a0 = Avx.LoadVector256(pLeft + i);
                    var a1 = Avx.LoadVector256(pLeft + i + width);
                    var res0 = Avx.Multiply(a0, mul);
                    var res1 = Avx.Multiply(a1, mul);
                    Avx.Store(pResult + i, res0);
                    Avx.Store(pResult + i + width, res1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatAvxConst_2xUnroll(ReadOnlySpan<float> left, float value, Span<float> result) => MulFloatAvx2Const_2xUnroll(left, value, result);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatSse41Const_2xUnroll(ReadOnlySpan<float> left, float value, Span<float> result)
        {
            int len = left.Length;
            int width = Vector128<float>.Count;
            int unroll = width * 2;
            var mul = Vector128.Create(value);
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
                    var a0 = Sse.LoadVector128(pLeft + i);
                    var a1 = Sse.LoadVector128(pLeft + i + width);
                    var res0 = Sse.Multiply(a0, mul);
                    var res1 = Sse.Multiply(a1, mul);
                    Sse.Store(pResult + i, res0);
                    Sse.Store(pResult + i + width, res1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void MulFloatSse2Const_2xUnroll(ReadOnlySpan<float> left, float value, Span<float> result) => MulFloatSse41Const_2xUnroll(left, value, result);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static void MulFloatScalarConst_2xUnroll(ReadOnlySpan<float> left, float value, Span<float> result)
        {
            for (int i = 0; i < left.Length; i++)
                result[i] = left[i] * value;
        }
    }
}