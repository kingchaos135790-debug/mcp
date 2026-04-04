using System;
using System.Diagnostics;
using System.Numerics;
using System.Runtime.CompilerServices;
using System.Runtime.Intrinsics;
using System.Runtime.Intrinsics.X86;

namespace MyProject
{
    public static partial class SIMDMath
    {
        // =============================
        // Public API
        // =============================

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void AllMul(this Span<Vector3> left, ReadOnlySpan<Vector3> right)
        {
            if (left.Length != right.Length) throw new ArgumentException("Length mismatch");
            // In a real implementation, this would call a dispatcher like:
            // s_v3Ops.Multiply(left, right);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void AllMul(this Span<Vector3> left, Vector3 value)
        {
            // In a real implementation, this would call a dispatcher like:
            // s_v3Ops.Multiply(left, value);
        }

        // =============================
        // Internal AVX Implementation
        // =============================

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void MultiplyVector3Avx2Entry(Span<Vector3> left, ReadOnlySpan<Vector3> right)
        {
            const int vectorsPerLoop = 8;
            int len = left.Length;
#if DEBUG
            Debug.Assert(left.Length == right.Length, "Spans must have the same length.");
            Debug.Assert(len % vectorsPerLoop == 0 && len != 0,
                "Span length must be a non-zero multiple of 8 for this optimized method.");
#endif
            fixed (Vector3* pLeft = left)
            fixed (Vector3* pRight = right)
            {
#if DEBUG
                var leftAddress = (UIntPtr)pLeft;
                var rightAddress = (UIntPtr)pRight;
                var byteLength = (UIntPtr)(len * sizeof(Vector3));
                bool overlap = leftAddress < rightAddress + byteLength && rightAddress < leftAddress + byteLength;
                Debug.Assert(!overlap, "Input spans must not overlap (alias).");
#endif
                for (int i = 0; i < len; i += vectorsPerLoop)
                {
                    float* pl = (float*)(pLeft + i);
                    float* pr = (float*)(pRight + i);

                    var left0 = Avx.LoadVector256(pl);
                    var left1 = Avx.LoadVector256(pl + 8);
                    var left2 = Avx.LoadVector256(pl + 16);

                    var right0 = Avx.LoadVector256(pr);
                    var right1 = Avx.LoadVector256(pr + 8);
                    var right2 = Avx.LoadVector256(pr + 16);

                    Transpose8x3(left0, left1, left2, out var leftX, out var leftY, out var leftZ);
                    Transpose8x3(right0, right1, right2, out var rightX, out var rightY, out var rightZ);

                    var resultX = Avx.Multiply(leftX, rightX);
                    var resultY = Avx.Multiply(leftY, rightY);
                    var resultZ = Avx.Multiply(leftZ, rightZ);

                    Untranspose8x3(resultX, resultY, resultZ, out var final0, out var final1, out var final2);

                    Avx.Store(pl, final0);
                    Avx.Store(pl + 8, final1);
                    Avx.Store(pl + 16, final2);
                }
            }
        }
        
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void MultiplyVector3Avx2ConstEntry(Span<Vector3> left, Vector3 value)
        {
            const int vectorsPerLoop = 8;
            int len = left.Length;
#if DEBUG
            Debug.Assert(len % vectorsPerLoop == 0 && len != 0,
                "Span length must be a non-zero multiple of 8 for this optimized method.");
#endif
            var valX = Vector256.Create(value.X);
            var valY = Vector256.Create(value.Y);
            var valZ = Vector256.Create(value.Z);

            fixed (Vector3* pLeft = left)
            {
                for (int i = 0; i < len; i += vectorsPerLoop)
                {
                    float* pl = (float*)(pLeft + i);

                    var left0 = Avx.LoadVector256(pl);
                    var left1 = Avx.LoadVector256(pl + 8);
                    var left2 = Avx.LoadVector256(pl + 16);

                    Transpose8x3(left0, left1, left2, out var leftX, out var leftY, out var leftZ);

                    var resultX = Avx.Multiply(leftX, valX);
                    var resultY = Avx.Multiply(leftY, valY);
                    var resultZ = Avx.Multiply(leftZ, valZ);

                    Untranspose8x3(resultX, resultY, resultZ, out var final0, out var final1, out var final2);

                    Avx.Store(pl, final0);
                    Avx.Store(pl + 8, final1);
                    Avx.Store(pl + 16, final2);
                }
            }
        }


        // =============================
        // Internal SSE Implementation
        // =============================

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void MultiplyVector3Sse41Entry(Span<Vector3> left, ReadOnlySpan<Vector3> right)
        {
            const int vectorsPerLoop = 4;
            int len = left.Length;
#if DEBUG
            Debug.Assert(left.Length == right.Length, "Spans must have the same length.");
            Debug.Assert(len % vectorsPerLoop == 0 && len != 0,
                "Span length must be a non-zero multiple of 4 for this optimized method.");
#endif
            fixed (Vector3* pLeft = left)
            fixed (Vector3* pRight = right)
            {
#if DEBUG
                var leftAddress = (UIntPtr)pLeft;
                var rightAddress = (UIntPtr)pRight;
                var byteLength = (UIntPtr)(len * sizeof(Vector3));
                bool overlap = leftAddress < rightAddress + byteLength && rightAddress < leftAddress + byteLength;
                Debug.Assert(!overlap, "Input spans must not overlap (alias).");
#endif
                for (int i = 0; i < len; i += vectorsPerLoop)
                {
                    float* pl = (float*)(pLeft + i);
                    float* pr = (float*)(pRight + i);
                    
                    var left0 = Sse.LoadVector128(pl);
                    var left1 = Sse.LoadVector128(pl + 4);
                    var left2 = Sse.LoadVector128(pl + 8);
                    
                    var right0 = Sse.LoadVector128(pr);
                    var right1 = Sse.LoadVector128(pr + 4);
                    var right2 = Sse.LoadVector128(pr + 8);

                    Transpose4x3(left0, left1, left2, out var leftX, out var leftY, out var leftZ);
                    Transpose4x3(right0, right1, right2, out var rightX, out var rightY, out var rightZ);

                    var resultX = Sse.Multiply(leftX, rightX);
                    var resultY = Sse.Multiply(leftY, rightY);
                    var resultZ = Sse.Multiply(leftZ, rightZ);

                    Untranspose4x3(resultX, resultY, resultZ, out var final0, out var final1, out var final2);

                    Sse.Store(pl, final0);
                    Sse.Store(pl + 4, final1);
                    Sse.Store(pl + 8, final2);
                }
            }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void MultiplyVector3Sse41ConstEntry(Span<Vector3> left, Vector3 value)
        {
            const int vectorsPerLoop = 4;
            int len = left.Length;
#if DEBUG
            Debug.Assert(len % vectorsPerLoop == 0 && len != 0,
                "Span length must be a non-zero multiple of 4 for this optimized method.");
#endif
            var valX = Vector128.Create(value.X);
            var valY = Vector128.Create(value.Y);
            var valZ = Vector128.Create(value.Z);

            fixed (Vector3* pLeft = left)
            {
                for (int i = 0; i < len; i += vectorsPerLoop)
                {
                    float* pl = (float*)(pLeft + i);

                    var left0 = Sse.LoadVector128(pl);
                    var left1 = Sse.LoadVector128(pl + 4);
                    var left2 = Sse.LoadVector128(pl + 8);

                    Transpose4x3(left0, left1, left2, out var leftX, out var leftY, out var leftZ);

                    var resultX = Sse.Multiply(leftX, valX);
                    var resultY = Sse.Multiply(leftY, valY);
                    var resultZ = Sse.Multiply(leftZ, valZ);

                    Untranspose4x3(resultX, resultY, resultZ, out var final0, out var final1, out var final2);

                    Sse.Store(pl, final0);
                    Sse.Store(pl + 4, final1);
                    Sse.Store(pl + 8, final2);
                }
            }
        }
        
        // =============================
        // Internal Scalar Implementation
        // =============================

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static void MultiplyVector3ScalarEntry(Span<Vector3> left, ReadOnlySpan<Vector3> right)
        {
            for (int i = 0; i < left.Length; i++)
            {
                left[i] = Vector3.Multiply(left[i], right[i]);
            }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static void MultiplyVector3ScalarConstEntry(Span<Vector3> left, Vector3 value)
        {
            for (int i = 0; i < left.Length; i++)
            {
                left[i] = Vector3.Multiply(left[i], value);
            }
        }
    }
}