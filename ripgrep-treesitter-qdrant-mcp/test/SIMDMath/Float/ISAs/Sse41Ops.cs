using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;

namespace MyProject
{
    public static partial class SIMDMath
    {
        private sealed partial class Sse41FloatOps : IFloatOps
        {
            internal static readonly Sse41FloatOps Instance = new Sse41FloatOps();
            private Sse41FloatOps() { }
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => AddFloatSse41_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, float value) => AddFloatSse41Const_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add(Span<float> left, ReadOnlySpan<float> right) => Add_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add(Span<float> left, float value) => Add_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => SubFloatSse41_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, float value) => SubFloatSse41Const_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub(Span<float> left, ReadOnlySpan<float> right) => Sub_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub(Span<float> left, float value) => Sub_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => MulFloatSse41_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, float value) => MulFloatSse41Const_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul(Span<float> left, ReadOnlySpan<float> right) => Mul_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul(Span<float> left, float value) => Mul_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => DivFloatSse41_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, float value) => DivFloatSse41Const_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div(Span<float> left, ReadOnlySpan<float> right) => Div_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div(Span<float> left, float value) => Div_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend) => FmaFloatSse41_2xUnroll(left, multiplicand, addend);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, float multiplicand, float addend) => FmaFloatSse41Const_2xUnroll(left, multiplicand, addend);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend) => Fma_2xUnroll(left, multiplicand, addend);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma(Span<float> left, float multiplicand, float addend) => Fma_2xUnroll(left, multiplicand, addend);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Exp(Span<float> values) => ExpFloatSse41(values);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                AddFloatSse41_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                AddFloatSse41Const_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                SubFloatSse41_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                SubFloatSse41Const_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                MulFloatSse41_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                MulFloatSse41Const_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                DivFloatSse41_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                DivFloatSse41Const_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend, Span<float> result)
            {
                FmaFloatSse41_2xUnroll(left, multiplicand, addend, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, float multiplicand, float addend, Span<float> result)
            {
                FmaFloatSse41Const_2xUnroll(left, multiplicand, addend, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Exp(Span<float> values, Span<float> result)
            {
                ExpFloatSse41(values, result);
            }
        }
    }
}