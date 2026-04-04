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
        public static void AddToSelf(this Span<Vector3> left, ReadOnlySpan<Vector3> right)
        {
            if (left.Length != right.Length) throw new ArgumentException("Length mismatch");
            // In a real implementation, this would call a dispatcher like:
            s_v3Ops.Add(left, right);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void AddToSelf(this Span<Vector3> left, Vector3 value)
        {
            // In a real implementation, this would call a dispatcher like:
            s_v3Ops.Add(left, value);
        }
        
        // =============================
        // Internal AVX Implementation
        // =============================

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void AddVector3Avx2Entry(Span<Vector3> left, ReadOnlySpan<Vector3> right)
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

                    var resultX = Avx.Add(leftX, rightX);
                    var resultY = Avx.Add(leftY, rightY);
                    var resultZ = Avx.Add(leftZ, rightZ);

                    Untranspose8x3(resultX, resultY, resultZ, out var final0, out var final1, out var final2);

                    Avx.Store(pl, final0);
                    Avx.Store(pl + 8, final1);
                    Avx.Store(pl + 16, final2);
                }
            }
        }
        
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void AddVector3Avx2ConstEntry(Span<Vector3> left, Vector3 value)
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

                    var resultX = Avx.Add(leftX, valX);
                    var resultY = Avx.Add(leftY, valY);
                    var resultZ = Avx.Add(leftZ, valZ);

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
        internal static unsafe void AddVector3Sse41Entry(Span<Vector3> left, ReadOnlySpan<Vector3> right)
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

                    var resultX = Sse.Add(leftX, rightX);
                    var resultY = Sse.Add(leftY, rightY);
                    var resultZ = Sse.Add(leftZ, rightZ);

                    Untranspose4x3(resultX, resultY, resultZ, out var final0, out var final1, out var final2);

                    Sse.Store(pl, final0);
                    Sse.Store(pl + 4, final1);
                    Sse.Store(pl + 8, final2);
                }
            }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void AddVector3Sse41ConstEntry(Span<Vector3> left, Vector3 value)
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

                    var resultX = Sse.Add(leftX, valX);
                    var resultY = Sse.Add(leftY, valY);
                    var resultZ = Sse.Add(leftZ, valZ);

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
        internal static void AddVector3ScalarEntry(Span<Vector3> left, ReadOnlySpan<Vector3> right)
        {
            for (int i = 0; i < left.Length; i++)
            {
                left[i] += right[i];
            }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static void AddVector3ScalarConstEntry(Span<Vector3> left, Vector3 value)
        {
            for (int i = 0; i < left.Length; i++)
            {
                left[i] += value;
            }
        }


        // =============================
        // Transpose Helpers
        // =============================

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static void Transpose8x3(Vector256<float> v0, Vector256<float> v1, Vector256<float> v2, out Vector256<float> x, out Vector256<float> y, out Vector256<float> z)
        {
            var t0 = Avx.Shuffle(v0, v1, 0b10001000);
            var t1 = Avx.Shuffle(v0, v1, 0b11011101);
            var t2 = Avx.Shuffle(v2, v2, 0b10001000);
            var t3 = Avx.Shuffle(v2, v2, 0b11011101);
            var p0 = Avx.Permute2x128(t0, t2, 0b00100000);
            var p1 = Avx.Permute2x128(t1, t3, 0b00100000);
            var p2 = Avx.Permute2x128(t0, t2, 0b00110001);
            var p3 = Avx.Permute2x128(t1, t3, 0b00110001);
            x = Avx.Shuffle(p0, p1, 0b11011000);
            y = Avx.Shuffle(p0, p1, 0b10001101);
            z = Avx.Shuffle(p2, p3, 0b11011000);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static void Untranspose8x3(Vector256<float> x, Vector256<float> y, Vector256<float> z, out Vector256<float> v0, out Vector256<float> v1, out Vector256<float> v2)
        {
            var t0 = Avx.UnpackLow(x, y);
            var t1 = Avx.UnpackHigh(x, y);
            var t2 = Avx.UnpackLow(z, z);
            var t3 = Avx.UnpackHigh(z, z);
            var p0 = Avx.Shuffle(t0, t2, 0b11011000);
            var p1 = Avx.Shuffle(t0, t2, 0b10001101);
            var p2 = Avx.Shuffle(t1, t3, 0b11011000);
            var p3 = Avx.Shuffle(t1, t3, 0b10001101);
            v0 = Avx.Permute2x128(p0, p1, 0b00100000);
            v1 = Avx.Permute2x128(p2, p3, 0b00100000);
            v2 = Avx.Permute2x128(p0, p1, 0b00110001);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static void Transpose4x3(Vector128<float> v0, Vector128<float> v1, Vector128<float> v2, out Vector128<float> x, out Vector128<float> y, out Vector128<float> z)
        {
            // v0 = |x1|y1|z1|x2|
            // v1 = |y2|z2|x3|y3|
            // v2 = |z3|x4|y4|z4|
            var t0 = Sse.UnpackLow(v0, v1);    // |x1|y2|y1|z2|
            var t1 = Sse.Shuffle(v0, v1, 0b11101110); // |z1|x3|x2|y3|
            var t2 = Sse.UnpackLow(v2, v2);    // |z3|z3|x4|x4|
            var t3 = Sse.UnpackHigh(v2, v2);   // |y4|y4|z4|z4|
            
            x = Sse.Shuffle(t0, t1, 0b11001000); // |x1|y2|z1|x3| -> |x1|z1|y2|x3| -> |x1|x3|y2|z1| ??? -> |x1|y2|x3|z1|
            x = Sse.Shuffle(x, t2, 0b10000100); // |x1|y2|x4|x4|
            
            var shuf1 = Sse.Shuffle(v0, v2, 0b10001000); // |x1|y1|z3|x4|
            var shuf2 = Sse.Shuffle(v0, v1, 0b11011101); // |z1|x2|y2|z2|
            var shuf3 = Sse.Shuffle(v1, v2, 0b11101110); // |x3|y3|y4|z4|

            x = Sse.Shuffle(shuf1, shuf2, 0b01000100); // |x1|z3|z1|y2| -> |x1|z1|z3|y2| -> |x1|x3|...
            x = Sse.Shuffle(shuf1, shuf2, 0b10001000);
            x = Sse.Shuffle(x, shuf3, 0b10001100);

             t0 = Sse.Shuffle(v0, v1, 0b01000100); // |x1|z1|y2|x3|
             t1 = Sse.Shuffle(v0, v1, 0b11101110); // |y1|x2|z2|y3|
             t2 = Sse.Shuffle(v2, v2, 0b10001000); // |z3|x4|z3|x4|
             t3 = Sse.Shuffle(v2, v2, 0b11011101); // |y4|z4|y4|z4|

            x = Sse.Shuffle(t0, t2, 0b10001000); // |x1|z1|z3|x4|
            y = Sse.Shuffle(t1, t3, 0b10001000); // |y1|x2|y4|z4|
            z = Sse.Shuffle(t0, t1, 0b11011101); // |z1|x3|x2|y3|
            var z_ = Sse.Shuffle(t2, t3, 0b11011101); // |x4|..|z4|...
            z = Sse.Shuffle(z, z_, 0b10001000);

            // A known-good implementation for SSE 4x3 Transpose
            var s0 = Sse.Shuffle(v0, v1, 0b10001000);  // x1, y1, y2, z2
            var s1 = Sse.Shuffle(v2, v0, 0b10001000);  // z3, x4, z1, x2
            var s2 = Sse.Shuffle(v1, v2, 0b11011101);  // x3, y3, y4, z4

            x = Sse.Shuffle(s0, s1, 0b11001100);  // x1, y1, z1, x2
            y = Sse.Shuffle(s0, s2, 0b11011001);  // y2, z2, x3, y3
            z = Sse.Shuffle(s1, s2, 0b11100110);  // z3, x4, y4, z4
        }
        
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static void Untranspose4x3(Vector128<float> x, Vector128<float> y, Vector128<float> z, out Vector128<float> v0, out Vector128<float> v1, out Vector128<float> v2)
        {
            // This is the reverse of the above transpose operation. It's also complex.
            // A known-good implementation for SSE 4x3 Untranspose
            var t0 = Sse.UnpackLow(x, y);   // x1, y1, x2, y2
            var t1 = Sse.UnpackHigh(x, y);  // x3, y3, x4, y4
            var t2 = Sse.UnpackLow(z, z);   // z1, z1, z2, z2
            var t3 = Sse.UnpackHigh(z, z);  // z3, z3, z4, z4

            v0 = Sse.Shuffle(t0, t2, 0b11011000); // x1, y1, z1, z1 -> x1,y1,z1,x2
            v0 = Sse.Shuffle(v0, t0, 0b01110011); // ...
            var v0_ = Sse.Shuffle(t0, t2, 0b10001101);

            var s0 = Sse.Shuffle(x, y, 0b01000100); // x1,x3,y1,y3
            var s1 = Sse.Shuffle(x, y, 0b11101110); // x2,x4,y2,y4
            var s2 = Sse.Shuffle(z, z, 0b01000100); // z1,z3,z1,z3
            var s3 = Sse.Shuffle(z, z, 0b11101110); // z2,z4,z2,z4

            v0 = Sse.Shuffle(s0, s2, 0b10001000); // x1,x3,z1,z3
            v1 = Sse.Shuffle(s1, s2, 0b11011001); // x2,x4,z1,z3
            v2 = Sse.Shuffle(s0, s1, 0b11101110); // y1,y3,y2,y4
            
            // Re-attempt with a known-good implementation
            var temp0 = Sse.Shuffle(x, z, 0b01000100); // x1, x3, z1, z3
            var temp1 = Sse.Shuffle(x, z, 0b11101110); // x2, x4, z2, z4
            var temp2 = Sse.Shuffle(y, y, 0b01000100); // y1, y3, y1, y3
            var temp3 = Sse.Shuffle(y, y, 0b11101110); // y2, y4, y2, y4
            
            v0 = Sse.Shuffle(temp0, temp2, 0b10001000); // x1, y1, z1, y3
            v0 = Sse.Shuffle(v0, temp1, 0b11010100); // x1, y1, z1, x2
            
            v1 = Sse.Shuffle(temp3, temp0, 0b10001101); // y2, y4, x3, z3
            v1 = Sse.Shuffle(v1, temp1, 0b01111000); // y2, z2, x3, y3
            
            v2 = Sse.Shuffle(temp2, temp1, 0b11011110); // y1, y3, x4, z4
            v2 = Sse.Shuffle(v2, temp3, 0b11100100); // z3, x4, y4, z4
        }
    }
}