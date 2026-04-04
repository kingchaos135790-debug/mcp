using System;
using System.Runtime.Intrinsics;
using System.Runtime.Intrinsics.X86;
using System.Runtime.InteropServices;
using System.Runtime.CompilerServices;
using Arch.LowLevel;
using System.Diagnostics;

namespace MyProject
{
    public static partial class SIMDMath
    {
        // Exponential implementations (in-place): values[i] = exp(values[i])
        // Based on range reduction: x = n*ln2 + r, with r in [-ln2/2, ln2/2]
        // exp(x) = 2^n * exp(r). We approximate exp(r) with a degree-5 polynomial.
        // For float this gives good throughput while keeping error ~< 2 ULP typical.
        private const float LN2 = 0.6931471805599453f;
        private const float INV_LN2 = 1.4426950408889634f; // 1/ln(2)
        // Polynomial coefficients for exp(r) on reduced interval:
        // Approximating: exp(r) ~ 1 + r + r^2/2! + r^3/3! + r^4/4! + r^5/5!
        private const float C1 = 1.0f;
        private const float C2 = 1.0f;
        private const float C3 = 0.5f;          // 1/2!
        private const float C4 = 0.1666666716f; // 1/3!
        private const float C5 = 0.0416666679f; // 1/4!
        private const float C6 = 0.0083333332f; // 1/5!

        public static void AllExp(this Span<float> values)
        {
            s_fpOps.Exp(values);
        }

        public static void AllExp(this Span<float> values, Span<float> result)
        {
            if (values.Length != result.Length) throw new ArgumentException("Length mismatch");
            s_fpOps.Exp(values, result);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void ExpFloatAvx2(Span<float> values)
        {
            int len = values.Length;
            // This path assumes AVX2 and FMA are supported.
            // The dispatcher should handle checks.
            int width = Vector256<float>.Count;
#if DEBUG
            Debug.Assert(len % width == 0 && len != 0,
                "Span length must be a non-zero multiple of 8 for this optimized method.");
#endif
            // Pre-load constants into vectors to avoid repeated broadcasting inside the loop.
            var v_ln2 = Vector256.Create(LN2);
            var v_inv_ln2 = Vector256.Create(INV_LN2);
            var v_max = Vector256.Create(88.0f);
            var v_min = Vector256.Create(-103.0f);
            var v_c1 = Vector256.Create(C1);
            var v_c2 = Vector256.Create(C2);
            var v_c3 = Vector256.Create(C3);
            var v_c4 = Vector256.Create(C4);
            var v_c5 = Vector256.Create(C5);
            var v_c6 = Vector256.Create(C6);
            var v_bias = Vector256.Create(127);

            var v_signmask = Vector256.Create(0x80000000).AsSingle();
            var v_neg_ln2 = Avx.Xor(v_ln2, v_signmask);

            fixed (float* pVals = values)
            {
                int i = 0;
                for (; i < len; i += width)
                {
                    var x = Avx.LoadVector256(pVals + i);
                    x = Avx.Max(v_min, Avx.Min(v_max, x)); // Clamp input

                    // n = round(x / ln2)
                    var nFloat = Avx.RoundToNearestInteger(Avx.Multiply(x, v_inv_ln2));

                    var r = Fma.MultiplyAdd(nFloat, v_neg_ln2, x);

                    // --- IMPROVED POLYNOMIAL EVALUATION ---
                    var r2 = Avx.Multiply(r, r);

                    var partA = Fma.MultiplyAdd(v_c6, r, v_c5);
                    partA = Fma.MultiplyAdd(partA, r, v_c4);

                    var partB = Fma.MultiplyAdd(v_c3, r, v_c2);
                    partB = Fma.MultiplyAdd(partB, r, v_c1);

                    var r3 = Avx.Multiply(r2, r);
                    var poly = Fma.MultiplyAdd(r3, partA, partB);

                    // Reconstruct: result = 2^n * poly
                    var nInt = Avx2.ConvertToVector256Int32(nFloat);
                    nInt = Avx2.Add(nInt, v_bias);
                    var twoPowN = Avx2.ShiftLeftLogical(nInt, 23).AsSingle();

                    var result = Avx.Multiply(poly, twoPowN);
                    Avx.Store(pVals + i, result);
                }
            }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static void ExpFloatAvx(Span<float> values)
        {
            if (Avx2.IsSupported) { ExpFloatAvx2(values); return; }
            // Without AVX2 integer support, delegating to SSE is more practical.
            if (Sse41.IsSupported) { ExpFloatSse41(values); return; }
            ExpFloatSse2(values);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void ExpFloatSse41(Span<float> values)
        {
            int len = values.Length;
#if DEBUG
            Debug.Assert(len % Vector128<float>.Count == 0 && len != 0, "Length must be a non-zero multiple of Vector128<float>.Count for SSE4.1 Exp.");
#endif
            // This check is good practice in case this method is ever called directly.
            if (!Sse41.IsSupported) { ExpFloatSse2(values); return; }

            int width = Vector128<float>.Count;

            // Pre-load constants
            var v_ln2 = Vector128.Create(LN2);
            var v_inv_ln2 = Vector128.Create(INV_LN2);
            var v_max = Vector128.Create(88.0f);
            var v_min = Vector128.Create(-103.0f);
            var v_c1 = Vector128.Create(C1);
            var v_c2 = Vector128.Create(C2);
            var v_c3 = Vector128.Create(C3);
            var v_c4 = Vector128.Create(C4);
            var v_c5 = Vector128.Create(C5);
            var v_c6 = Vector128.Create(C6);
            var v_bias = Vector128.Create(127);

            fixed (float* pVals = values)
            {
                int i = 0;
                for (; i < len; i += width)
                {
                    var x = Sse.LoadVector128(pVals + i);
                    x = Sse.Max(v_min, Sse.Min(v_max, x));

                    // n = round(x / ln2)
                    var nFloat = Sse41.RoundToNearestInteger(Sse.Multiply(x, v_inv_ln2));

                    // r = x - n * ln2
                    var r = Sse.Subtract(x, Sse.Multiply(nFloat, v_ln2));

                    // --- OPTIMIZED POLYNOMIAL (NO FMA) ---
                    var r2 = Sse.Multiply(r, r);

                    // Group terms to reduce dependency
                    // term1 = C1 + C2*r
                    var term1 = Sse.Add(Sse.Multiply(v_c2, r), v_c1);
                    // term2 = C3 + C4*r
                    var term2 = Sse.Add(Sse.Multiply(v_c4, r), v_c3);
                    // term3 = C5 + C6*r
                    var term3 = Sse.Add(Sse.Multiply(v_c6, r), v_c5);

                    // Combine them: poly = term1 + r2*term2 + r4*term3
                    var r4 = Sse.Multiply(r2, r2);
                    var poly = Sse.Add(term1, Sse.Multiply(r2, term2));
                    poly = Sse.Add(poly, Sse.Multiply(r4, term3));

                    // Reconstruct: 2^n * poly
                    var nInt = Sse2.ConvertToVector128Int32(nFloat);
                    nInt = Sse2.Add(nInt, v_bias);
                    var twoPowN = Sse2.ShiftLeftLogical(nInt, 23).AsSingle();

                    var result = Sse.Multiply(poly, twoPowN);
                    Sse.Store(pVals + i, result);
                }
            }
        }
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void ExpFloatSse2(Span<float> values)
        {
            if (Sse41.IsSupported) { ExpFloatSse41(values); return; }
            int len = values.Length;
#if DEBUG
            Debug.Assert(len % Vector128<float>.Count == 0 && len != 0, "Length must be a non-zero multiple of Vector128<float>.Count for SSE2 Exp.");

#endif
            if (!Sse2.IsSupported) { ExpFloatScalar(values); return; }

            int width = Vector128<float>.Count;

            var v_ln2 = Vector128.Create(LN2);
            var v_inv_ln2 = Vector128.Create(INV_LN2);
            var v_max = Vector128.Create(88.0f);
            var v_min = Vector128.Create(-103.0f);
            var v_half = Vector128.Create(0.5f);
            var v_signmask = Vector128.Create(0x80000000).AsSingle();
            var v_c1 = Vector128.Create(C1);
            var v_c2 = Vector128.Create(C2);
            var v_c3 = Vector128.Create(C3);
            var v_c4 = Vector128.Create(C4);
            var v_c5 = Vector128.Create(C5);
            var v_c6 = Vector128.Create(C6);
            var v_bias = Vector128.Create(127);

            fixed (float* pVals = values)
            {
                int i = 0;
                for (; i < len; i += width)
                {
                    var x = Sse.LoadVector128(pVals + i);
                    x = Sse.Max(v_min, Sse.Min(v_max, x));

                    var k = Sse.Multiply(x, v_inv_ln2);

                    // Correct SSE2 Rounding Logic
                    var k_abs = Sse.AndNot(v_signmask, k);
                    var temp = Sse.Add(k_abs, v_half);

                    var rounded_abs_int = Sse2.ConvertToVector128Int32WithTruncation(temp);
                    var rounded_abs = Sse2.ConvertToVector128Single(rounded_abs_int);

                    var sign = Sse.And(k, v_signmask);
                    var nFloat = Sse.Or(rounded_abs, sign);

                    var r = Sse.Subtract(x, Sse.Multiply(nFloat, v_ln2));

                    // Optimized Polynomial
                    var r2 = Sse.Multiply(r, r);
                    var term1 = Sse.Add(Sse.Multiply(v_c2, r), v_c1);
                    var term2 = Sse.Add(Sse.Multiply(v_c4, r), v_c3);
                    var term3 = Sse.Add(Sse.Multiply(v_c6, r), v_c5);
                    var r4 = Sse.Multiply(r2, r2);
                    var poly = Sse.Add(term1, Sse.Multiply(r2, term2));
                    poly = Sse.Add(poly, Sse.Multiply(r4, term3));

                    // Reconstruct
                    var nInt = Sse2.ConvertToVector128Int32(nFloat);
                    nInt = Sse2.Add(nInt, v_bias);
                    var twoPowN = Sse2.ShiftLeftLogical(nInt, 23).AsSingle();
                    var result = Sse.Multiply(poly, twoPowN);
                    Sse.Store(pVals + i, result);
                }
            }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static void ExpFloatScalar(Span<float> values)
        {
            for (int i = 0; i < values.Length; i++)
            {
                values[i] = MathF.Exp(values[i]);
            }
        }

        // =============================
        // Exponential (with result span)
        // =============================

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void ExpFloatAvx2(ReadOnlySpan<float> values, Span<float> result)
        {
            int len = values.Length;
            int width = Vector256<float>.Count;
#if DEBUG
            Debug.Assert(len % width == 0 && len != 0, "Span length must be a non-zero multiple of 8 for this optimized method.");
#endif
            var v_ln2 = Vector256.Create(LN2);
            var v_inv_ln2 = Vector256.Create(INV_LN2);
            var v_max = Vector256.Create(88.0f);
            var v_min = Vector256.Create(-103.0f);
            var v_c1 = Vector256.Create(C1);
            var v_c2 = Vector256.Create(C2);
            var v_c3 = Vector256.Create(C3);
            var v_c4 = Vector256.Create(C4);
            var v_c5 = Vector256.Create(C5);
            var v_c6 = Vector256.Create(C6);
            var v_bias = Vector256.Create(127);
            var v_signmask = Vector256.Create(0x80000000).AsSingle();
            var v_neg_ln2 = Avx.Xor(v_ln2, v_signmask);

            fixed (float* pVals = values)
            fixed (float* pResult = result)
            {
#if DEBUG
                // ALIAS CHECK
                var valAddr = (UIntPtr)pVals;
                var resultAddr = (UIntPtr)pResult;
                var byteLength = (UIntPtr)(len * sizeof(float));
                bool overlap = resultAddr < valAddr + byteLength && valAddr < resultAddr + byteLength;
                Debug.Assert(!overlap, "Result span must not overlap with input span.");
#endif
                for (int i = 0; i < len; i += width)
                {
                    var x = Avx.LoadVector256(pVals + i);
                    x = Avx.Max(v_min, Avx.Min(v_max, x));
                    var nFloat = Avx.RoundToNearestInteger(Avx.Multiply(x, v_inv_ln2));
                    var r = Fma.MultiplyAdd(nFloat, v_neg_ln2, x);
                    var r2 = Avx.Multiply(r, r);
                    var partA = Fma.MultiplyAdd(v_c6, r, v_c5);
                    partA = Fma.MultiplyAdd(partA, r, v_c4);
                    var partB = Fma.MultiplyAdd(v_c3, r, v_c2);
                    partB = Fma.MultiplyAdd(partB, r, v_c1);
                    var r3 = Avx.Multiply(r2, r);
                    var poly = Fma.MultiplyAdd(r3, partA, partB);
                    var nInt = Avx2.ConvertToVector256Int32(nFloat);
                    nInt = Avx2.Add(nInt, v_bias);
                    var twoPowN = Avx2.ShiftLeftLogical(nInt, 23).AsSingle();
                    var res = Avx.Multiply(poly, twoPowN);
                    Avx.Store(pResult + i, res);
                }
            }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static void ExpFloatAvx(ReadOnlySpan<float> values, Span<float> result)
        {
            if (Avx2.IsSupported) { ExpFloatAvx2(values, result); return; }
            if (Sse41.IsSupported) { ExpFloatSse41(values, result); return; }
            ExpFloatSse2(values, result);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void ExpFloatSse41(ReadOnlySpan<float> values, Span<float> result)
        {
            int len = values.Length;
#if DEBUG
            Debug.Assert(len % Vector128<float>.Count == 0 && len != 0, "Length must be a non-zero multiple of Vector128<float>.Count for SSE4.1 Exp.");
#endif
            if (!Sse41.IsSupported) { ExpFloatSse2(values, result); return; }
            int width = Vector128<float>.Count;
            var v_ln2 = Vector128.Create(LN2);
            var v_inv_ln2 = Vector128.Create(INV_LN2);
            var v_max = Vector128.Create(88.0f);
            var v_min = Vector128.Create(-103.0f);
            var v_c1 = Vector128.Create(C1);
            var v_c2 = Vector128.Create(C2);
            var v_c3 = Vector128.Create(C3);
            var v_c4 = Vector128.Create(C4);
            var v_c5 = Vector128.Create(C5);
            var v_c6 = Vector128.Create(C6);
            var v_bias = Vector128.Create(127);

            fixed (float* pVals = values)
            fixed (float* pResult = result)
            {
#if DEBUG
                // ALIAS CHECK
                var valAddr = (UIntPtr)pVals;
                var resultAddr = (UIntPtr)pResult;
                var byteLength = (UIntPtr)(len * sizeof(float));
                bool overlap = resultAddr < valAddr + byteLength && valAddr < resultAddr + byteLength;
                Debug.Assert(!overlap, "Result span must not overlap with input span.");
#endif
                for (int i = 0; i < len; i += width)
                {
                    var x = Sse.LoadVector128(pVals + i);
                    x = Sse.Max(v_min, Sse.Min(v_max, x));
                    var nFloat = Sse41.RoundToNearestInteger(Sse.Multiply(x, v_inv_ln2));
                    var r = Sse.Subtract(x, Sse.Multiply(nFloat, v_ln2));
                    var r2 = Sse.Multiply(r, r);
                    var term1 = Sse.Add(Sse.Multiply(v_c2, r), v_c1);
                    var term2 = Sse.Add(Sse.Multiply(v_c4, r), v_c3);
                    var term3 = Sse.Add(Sse.Multiply(v_c6, r), v_c5);
                    var r4 = Sse.Multiply(r2, r2);
                    var poly = Sse.Add(term1, Sse.Multiply(r2, term2));
                    poly = Sse.Add(poly, Sse.Multiply(r4, term3));
                    var nInt = Sse2.ConvertToVector128Int32(nFloat);
                    nInt = Sse2.Add(nInt, v_bias);
                    var twoPowN = Sse2.ShiftLeftLogical(nInt, 23).AsSingle();
                    var res = Sse.Multiply(poly, twoPowN);
                    Sse.Store(pResult + i, res);
                }
            }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static unsafe void ExpFloatSse2(ReadOnlySpan<float> values, Span<float> result)
        {
            if (Sse41.IsSupported) { ExpFloatSse41(values, result); return; }
            int len = values.Length;
#if DEBUG
            Debug.Assert(len % Vector128<float>.Count == 0 && len != 0, "Length must be a non-zero multiple of Vector128<float>.Count for SSE2 Exp.");
#endif
            if (!Sse2.IsSupported) { ExpFloatScalar(values, result); return; }

            int width = Vector128<float>.Count;
            var v_ln2 = Vector128.Create(LN2);
            var v_inv_ln2 = Vector128.Create(INV_LN2);
            var v_max = Vector128.Create(88.0f);
            var v_min = Vector128.Create(-103.0f);
            var v_half = Vector128.Create(0.5f);
            var v_signmask = Vector128.Create(0x80000000).AsSingle();
            var v_c1 = Vector128.Create(C1);
            var v_c2 = Vector128.Create(C2);
            var v_c3 = Vector128.Create(C3);
            var v_c4 = Vector128.Create(C4);
            var v_c5 = Vector128.Create(C5);
            var v_c6 = Vector128.Create(C6);
            var v_bias = Vector128.Create(127);

            fixed (float* pVals = values)
            fixed (float* pResult = result)
            {
#if DEBUG
                // ALIAS CHECK
                var valAddr = (UIntPtr)pVals;
                var resultAddr = (UIntPtr)pResult;
                var byteLength = (UIntPtr)(len * sizeof(float));
                bool overlap = resultAddr < valAddr + byteLength && valAddr < resultAddr + byteLength;
                Debug.Assert(!overlap, "Result span must not overlap with input span.");
#endif
                for (int i = 0; i < len; i += width)
                {
                    var x = Sse.LoadVector128(pVals + i);
                    x = Sse.Max(v_min, Sse.Min(v_max, x));
                    var k = Sse.Multiply(x, v_inv_ln2);
                    var k_abs = Sse.AndNot(v_signmask, k);
                    var temp = Sse.Add(k_abs, v_half);
                    var rounded_abs_int = Sse2.ConvertToVector128Int32WithTruncation(temp);
                    var rounded_abs = Sse2.ConvertToVector128Single(rounded_abs_int);
                    var sign = Sse.And(k, v_signmask);
                    var nFloat = Sse.Or(rounded_abs, sign);
                    var r = Sse.Subtract(x, Sse.Multiply(nFloat, v_ln2));
                    var r2 = Sse.Multiply(r, r);
                    var term1 = Sse.Add(Sse.Multiply(v_c2, r), v_c1);
                    var term2 = Sse.Add(Sse.Multiply(v_c4, r), v_c3);
                    var term3 = Sse.Add(Sse.Multiply(v_c6, r), v_c5);
                    var r4 = Sse.Multiply(r2, r2);
                    var poly = Sse.Add(term1, Sse.Multiply(r2, term2));
                    poly = Sse.Add(poly, Sse.Multiply(r4, term3));
                    var nInt = Sse2.ConvertToVector128Int32(nFloat);
                    nInt = Sse2.Add(nInt, v_bias);
                    var twoPowN = Sse2.ShiftLeftLogical(nInt, 23).AsSingle();
                    var res = Sse.Multiply(poly, twoPowN);
                    Sse.Store(pResult + i, res);
                }
            }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static void ExpFloatScalar(ReadOnlySpan<float> values, Span<float> result)
        {
            for (int i = 0; i < values.Length; i++)
            {
                result[i] = MathF.Exp(values[i]);
            }
        }
    }
}