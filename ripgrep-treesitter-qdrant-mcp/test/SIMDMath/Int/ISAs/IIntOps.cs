using System;
using System.Runtime.CompilerServices;

namespace MyProject
{
    public static partial class SIMDMath
    {
        // Strategy interface implemented by hardware-specific integer singletons
        private interface IIntOps
        {
            void Add_2xUnroll(Span<int> left, ReadOnlySpan<int> right);
            void Add_2xUnroll(Span<int> left, ReadOnlySpan<int> right, Span<int> result);
            void Add_2xUnroll(Span<int> left, int value);
            void Add_2xUnroll(Span<int> left, int value, Span<int> result);
            void Sub_2xUnroll(Span<int> left, ReadOnlySpan<int> right);
            void Sub_2xUnroll(Span<int> left, ReadOnlySpan<int> right, Span<int> result);
            void Sub_2xUnroll(Span<int> left, int value);
            void Sub_2xUnroll(Span<int> left, int value, Span<int> result);
            void Mul_2xUnroll(Span<int> left, ReadOnlySpan<int> right);
            void Mul_2xUnroll(Span<int> left, ReadOnlySpan<int> right, Span<int> result);
            void Mul_2xUnroll(Span<int> left, int value);
            void Mul_2xUnroll(Span<int> left, int value, Span<int> result);
            void Div_2xUnroll(Span<int> left, ReadOnlySpan<int> right);
            void Div_2xUnroll(Span<int> left, ReadOnlySpan<int> right, Span<int> result);
            void Div_2xUnroll(Span<int> left, int value);
            void Div_2xUnroll(Span<int> left, int value, Span<int> result);
            // In-place widen/misc ops could be added here if needed for ints
            void Add_4xUnroll(Span<int> left, ReadOnlySpan<int> right);
            void Add_4xUnroll(Span<int> left, ReadOnlySpan<int> right, Span<int> result);
            void Add_4xUnroll(Span<int> left, int value);
            void Add_4xUnroll(Span<int> left, int value, Span<int> result);
            void Sub_4xUnroll(Span<int> left, ReadOnlySpan<int> right);
            void Sub_4xUnroll(Span<int> left, ReadOnlySpan<int> right, Span<int> result);
            void Sub_4xUnroll(Span<int> left, int value);
            void Sub_4xUnroll(Span<int> left, int value, Span<int> result);
            void Mul_4xUnroll(Span<int> left, ReadOnlySpan<int> right);
            void Mul_4xUnroll(Span<int> left, ReadOnlySpan<int> right, Span<int> result);
            void Mul_4xUnroll(Span<int> left, int value);
            void Mul_4xUnroll(Span<int> left, int value, Span<int> result);
            void Div_4xUnroll(Span<int> left, ReadOnlySpan<int> right);
            void Div_4xUnroll(Span<int> left, ReadOnlySpan<int> right, Span<int> result);
            void Div_4xUnroll(Span<int> left, int value);
            void Div_4xUnroll(Span<int> left, int value, Span<int> result);
            void Add_1xUnroll(Span<int> left, ReadOnlySpan<int> right);
            void Add_1xUnroll(Span<int> left, ReadOnlySpan<int> right, Span<int> result);
            void Add_1xUnroll(Span<int> left, int value);
            void Add_1xUnroll(Span<int> left, int value, Span<int> result);
            void Sub_1xUnroll(Span<int> left, ReadOnlySpan<int> right);
            void Sub_1xUnroll(Span<int> left, ReadOnlySpan<int> right, Span<int> result);
            void Sub_1xUnroll(Span<int> left, int value);
            void Sub_1xUnroll(Span<int> left, int value, Span<int> result);
            void Mul_1xUnroll(Span<int> left, ReadOnlySpan<int> right);
            void Mul_1xUnroll(Span<int> left, ReadOnlySpan<int> right, Span<int> result);
            void Mul_1xUnroll(Span<int> left, int value);
            void Mul_1xUnroll(Span<int> left, int value, Span<int> result);
            void Div_1xUnroll(Span<int> left, ReadOnlySpan<int> right);
            void Div_1xUnroll(Span<int> left, ReadOnlySpan<int> right, Span<int> result);
            void Div_1xUnroll(Span<int> left, int value);
            void Div_1xUnroll(Span<int> left, int value, Span<int> result);
        }

    }
}

