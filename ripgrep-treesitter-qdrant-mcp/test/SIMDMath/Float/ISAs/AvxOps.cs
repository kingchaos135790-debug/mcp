using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;

namespace MyProject
{
    public static partial class SIMDMath
    {
        private sealed partial class AvxFloatOps : IFloatOps
        {
            internal static readonly AvxFloatOps Instance = new AvxFloatOps();
            private AvxFloatOps() { }
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => AddFloatAvx_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, float value) => AddFloatAvxConst_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => SubFloatAvx_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, float value) => SubFloatAvxConst_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => MulFloatAvx_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, float value) => MulFloatAvxConst_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => DivFloatAvx_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, float value) => DivFloatAvxConst_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend) => FmaFloatAvx_2xUnroll(left, multiplicand, addend);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, float multiplicand, float addend) => FmaFloatAvxConst_2xUnroll(left, multiplicand, addend);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Exp(Span<float> values) => ExpFloatAvx(values);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                AddFloatAvx_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                AddFloatAvxConst_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                SubFloatAvx_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                SubFloatAvxConst_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                MulFloatAvx_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                MulFloatAvxConst_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                DivFloatAvx_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                DivFloatAvxConst_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend, Span<float> result)
            {
                FmaFloatAvx_2xUnroll(left, multiplicand, addend, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, float multiplicand, float addend, Span<float> result)
            {
                FmaFloatAvxConst_2xUnroll(left, multiplicand, addend, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Exp(Span<float> values, Span<float> result)
            {
                ExpFloatAvx(values, result);
            }
        }
    }
}