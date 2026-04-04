using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;

namespace MyProject
{
    public static partial class SIMDMath
    {
        private sealed partial class Avx2FloatOps : IFloatOps
        {
            internal static readonly Avx2FloatOps Instance = new Avx2FloatOps();
            private Avx2FloatOps() { }
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => AddFloatAvx2_2xUnroll(left, right);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, float value) => AddFloatAvx2Const_2xUnroll(left, value);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => SubFloatAvx2_2xUnroll(left, right);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, float value) => SubFloatAvx2Const_2xUnroll(left, value);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => MulFloatAvx2_2xUnroll(left, right);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, float value) => MulFloatAvx2Const_2xUnroll(left, value);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => DivFloatAvx2_2xUnroll(left, right);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, float value) => DivFloatAvx2Const_2xUnroll(left, value);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend) => FmaFloatAvx2_2xUnroll(left, multiplicand, addend);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, float multiplicand, float addend) => FmaFloatAvx2Const_2xUnroll(left, multiplicand, addend);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Exp(Span<float> values) => ExpFloatAvx2(values);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                AddFloatAvx2_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                AddFloatAvx2Const_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                SubFloatAvx2_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                SubFloatAvx2Const_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                MulFloatAvx2_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                MulFloatAvx2Const_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                DivFloatAvx2_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]

            public void Div_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                DivFloatAvx2Const_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend, Span<float> result)
            {
                FmaFloatAvx2_2xUnroll(left, multiplicand, addend, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, float multiplicand, float addend, Span<float> result)
            {
                FmaFloatAvx2Const_2xUnroll(left, multiplicand, addend, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Exp(Span<float> values, Span<float> result)
            {
                ExpFloatAvx2(values, result);
            }
        }
    }
}