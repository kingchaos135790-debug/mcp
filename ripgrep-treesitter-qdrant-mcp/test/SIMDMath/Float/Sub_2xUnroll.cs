using System;
using System.Runtime.CompilerServices;
using System.Runtime.Intrinsics;
using System.Runtime.Intrinsics.X86;
using System.Diagnostics; // Added for Debug.Assert

namespace MyProject
{
    public static partial class SIMDMath
    {
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void Sub(this Span<float> left, ReadOnlySpan<float> right)
        {
            if (left.Length != right.Length) throw new ArgumentException("Length mismatch");
            s_fpOps.Sub_2xUnroll(left, right);
        }
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void Sub(this Span<float> left, float value)
        {
            s_fpOps.Sub_2xUnroll(left, value);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void Sub(this Span<float> left, ReadOnlySpan<float> right, Span<float> result)
        {
            if (left.Length != right.Length || left.Length != result.Length) throw new ArgumentException("Length mismatch");
            s_fpOps.Sub_2xUnroll(left, right, result);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void Sub(this Span<float> left, float value, Span<float> result)
        {
            if (left.Length != result.Length) throw new ArgumentException("Length mismatch");
            s_fpOps.Sub_2xUnroll(left, value, result);
        }

        // =============================
        // Subtraction (binary) - In-Place
        // =============================

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void SubFloatAvx2_2xUnroll(Span<float> left, ReadOnlySpan<float> right)
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
                    a0 = Avx.Subtract(a0, b0);
                    a1 = Avx.Subtract(a1, b1);
                    Avx.Store(pLeft + i, a0);
                    Avx.Store(pLeft + i + width, a1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatAvx_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => SubFloatAvx2_2xUnroll(left, right);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatSse41_2xUnroll(Span<float> left, ReadOnlySpan<float> right)
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
                    a0 = Sse.Subtract(a0, b0);
                    a1 = Sse.Subtract(a1, b1);
                    Sse.Store(pLeft + i, a0);
                    Sse.Store(pLeft + i + width, a1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatSse2_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => SubFloatSse41_2xUnroll(left, right);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static void SubFloatScalar_2xUnroll(Span<float> left, ReadOnlySpan<float> right)
        {
            for (int i = 0; i < left.Length; i++)
                left[i] -= right[i];
        }

        // =============================
        // Subtraction (constant) - In-Place
        // =============================

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatAvx2Const_2xUnroll(Span<float> left, float value)
        {
            int len = left.Length;
            int width = Vector256<float>.Count;
            int unroll = width * 2;
            var sub = Vector256.Create(value);

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
                    a0 = Avx.Subtract(a0, sub);
                    a1 = Avx.Subtract(a1, sub);
                    Avx.Store(pLeft + i, a0);
                    Avx.Store(pLeft + i + width, a1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatAvxConst_2xUnroll(Span<float> left, float value) => SubFloatAvx2Const_2xUnroll(left, value);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatSse41Const_2xUnroll(Span<float> left, float value)
        {
            int len = left.Length;
            int width = Vector128<float>.Count;
            int unroll = width * 2;
            var sub = Vector128.Create(value);
            fixed (float* pLeft = left)
            {
#if DEBUG
                Debug.Assert(len % unroll == 0 && len != 0, $"Span length must be a non-zero multiple of {unroll} for this optimized method.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var a0 = Sse.LoadVector128(pLeft + i);
                    var a1 = Sse.LoadVector128(pLeft + i + width);
                    a0 = Sse.Subtract(a0, sub);
                    a1 = Sse.Subtract(a1, sub);
                    Sse.Store(pLeft + i, a0);
                    Sse.Store(pLeft + i + width, a1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatSse2Const_2xUnroll(Span<float> left, float value) => SubFloatSse41Const_2xUnroll(left, value);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static void SubFloatScalarConst_2xUnroll(Span<float> left, float value)
        {
            for (int i = 0; i < left.Length; i++)
                left[i] -= value;
        }

        // =============================
        // Subtraction (binary) - With Result Span
        // =============================

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatAvx2_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> right, Span<float> result)
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

                // Check for overlap between result and left
                bool overlapRL = resultAddr < leftAddr + byteLength && leftAddr < resultAddr + byteLength;

                // Check for overlap between result and right
                bool overlapRR = resultAddr < rightAddr + byteLength && rightAddr < resultAddr + byteLength;

                Debug.Assert(!overlapRL && !overlapRR, "Result span must not overlap with input spans.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var a0 = Avx.LoadVector256(pLeft + i);
                    var b0 = Avx.LoadVector256(pRight + i);
                    var a1 = Avx.LoadVector256(pLeft + i + width);
                    var b1 = Avx.LoadVector256(pRight + i + width);
                    var res0 = Avx.Subtract(a0, b0);
                    var res1 = Avx.Subtract(a1, b1);
                    Avx.Store(pResult + i, res0);
                    Avx.Store(pResult + i + width, res1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatAvx_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> right, Span<float> result) => SubFloatAvx2_2xUnroll(left, right, result);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatSse41_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> right, Span<float> result)
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

                // Check for overlap between result and left
                bool overlapRL = resultAddr < leftAddr + byteLength && leftAddr < resultAddr + byteLength;

                // Check for overlap between result and right
                bool overlapRR = resultAddr < rightAddr + byteLength && rightAddr < resultAddr + byteLength;

                Debug.Assert(!overlapRL && !overlapRR, "Result span must not overlap with input spans.");
#endif
                for (int i = 0; i < len; i += unroll)
                {
                    var a0 = Sse.LoadVector128(pLeft + i);
                    var b0 = Sse.LoadVector128(pRight + i);
                    var a1 = Sse.LoadVector128(pLeft + i + width);
                    var b1 = Sse.LoadVector128(pRight + i + width);
                    var res0 = Sse.Subtract(a0, b0);
                    var res1 = Sse.Subtract(a1, b1);
                    Sse.Store(pResult + i, res0);
                    Sse.Store(pResult + i + width, res1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatSse2_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> right, Span<float> result) => SubFloatSse41_2xUnroll(left, right, result);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static void SubFloatScalar_2xUnroll(ReadOnlySpan<float> left, ReadOnlySpan<float> right, Span<float> result)
        {
            for (int i = 0; i < left.Length; i++)
                result[i] = left[i] - right[i];
        }

        // =============================
        // Subtraction (constant) - With Result Span
        // =============================

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatAvx2Const_2xUnroll(ReadOnlySpan<float> left, float value, Span<float> result)
        {
            int len = left.Length;
            int width = Vector256<float>.Count;
            int unroll = width * 2;
            var sub = Vector256.Create(value);
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
                    var res0 = Avx.Subtract(a0, sub);
                    var res1 = Avx.Subtract(a1, sub);
                    Avx.Store(pResult + i, res0);
                    Avx.Store(pResult + i + width, res1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatAvxConst_2xUnroll(ReadOnlySpan<float> left, float value, Span<float> result) => SubFloatAvx2Const_2xUnroll(left, value, result);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatSse41Const_2xUnroll(ReadOnlySpan<float> left, float value, Span<float> result)
        {
            int len = left.Length;
            int width = Vector128<float>.Count;
            int unroll = width * 2;
            var sub = Vector128.Create(value);
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
                    var res0 = Sse.Subtract(a0, sub);
                    var res1 = Sse.Subtract(a1, sub);
                    Sse.Store(pResult + i, res0);
                    Sse.Store(pResult + i + width, res1);
                }
            }
        }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static unsafe void SubFloatSse2Const_2xUnroll(ReadOnlySpan<float> left, float value, Span<float> result) => SubFloatSse41Const_2xUnroll(left, value, result);

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    internal static void SubFloatScalarConst_2xUnroll(ReadOnlySpan<float> left, float value, Span<float> result)
        {
            for (int i = 0; i < left.Length; i++)
                result[i] = left[i] - value;
        }
    }
}