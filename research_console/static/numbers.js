(function (root) {
  "use strict";
  // Bound derived decimal components from the unchanged v1 input/mark budgets.
  const MAX_INTEGER_DIGITS = 4_000_016;
  class NumericFormatError extends Error {}
  function halfEven(numerator, denominator) {
    let value = numerator / denominator;
    const remainder = numerator % denominator;
    if (
      2n * remainder > denominator ||
      (2n * remainder === denominator && value % 2n === 1n)
    )
      value++;
    return value;
  }
  function scientific(numerator, denominator, negative, places) {
    let exponent = numerator.toString().length - denominator.toString().length;
    if (
      exponent >= 0
        ? numerator < denominator * 10n ** BigInt(exponent)
        : numerator * 10n ** BigInt(-exponent) < denominator
    )
      exponent--;
    const precision = Math.max(1, Math.min(places, 8));
    const shift = precision - exponent;
    let coefficient =
      shift >= 0
        ? halfEven(numerator * 10n ** BigInt(shift), denominator)
        : halfEven(numerator, denominator * 10n ** BigInt(-shift));
    const scale = 10n ** BigInt(precision);
    if (coefficient >= 10n * scale) {
      coefficient /= 10n;
      exponent++;
    }
    const tail = (coefficient % scale)
      .toString()
      .padStart(precision, "0")
      .replace(/0+$/, "");
    return `≈ ${negative ? "-" : ""}${coefficient / scale}${tail ? "," + tail : ""}e${exponent >= 0 ? "+" : ""}${exponent}`;
  }
  function formatDecimal(value, places = 8, factor = 1) {
    if (
      typeof value !== "string" ||
      value.length > 2 * MAX_INTEGER_DIGITS + 2 ||
      !Number.isInteger(places) ||
      places < 0 ||
      places > 12 ||
      ![1, 100].includes(factor)
    )
      throw new NumericFormatError("Formato decimal inválido");
    let numerator, denominator;
    const fraction = value.split("/");
    if (fraction.length === 2) {
      if (
        fraction[0].replace(/^-/, "").length > MAX_INTEGER_DIGITS ||
        fraction[1].length > MAX_INTEGER_DIGITS ||
        !/^-?\d+$/.test(fraction[0]) ||
        !/^\d+$/.test(fraction[1])
      )
        throw new NumericFormatError("Formato decimal inválido");
      numerator = BigInt(fraction[0]);
      denominator = BigInt(fraction[1]);
    } else if (
      value.replace(/^-/, "").length <= MAX_INTEGER_DIGITS &&
      /^-?\d+$/.test(value)
    ) {
      numerator = BigInt(value);
      denominator = 1n;
    } else {
      const m =
        /^(-?)(\d{1,240})(?:\.(\d{1,240}))?(?:[eE]([+-]?\d{1,3}))?$/.exec(
          value,
        );
      if (!m || Math.abs(Number(m[4] || 0)) > 300)
        throw new NumericFormatError("Formato decimal inválido");
      numerator = BigInt((m[1] || "") + m[2] + (m[3] || ""));
      const shift = (m[3] || "").length - Number(m[4] || 0);
      denominator = shift >= 0 ? 10n ** BigInt(shift) : 1n;
      if (shift < 0) numerator *= 10n ** BigInt(-shift);
    }
    if (denominator <= 0n) throw new NumericFormatError("Divisor inválido");
    numerator *= BigInt(factor);
    const negative = numerator < 0n;
    if (negative) numerator = -numerator;
    const scale = 10n ** BigInt(places),
      scaled = numerator * scale;
    const rounded = halfEven(scaled, denominator);
    // A nonzero amount must not masquerade as exact zero; huge output is bounded.
    if (
      (numerator !== 0n && rounded === 0n) ||
      numerator >= denominator * 10n ** 24n
    )
      return scientific(numerator, denominator, negative, places);
    const whole = (rounded / scale)
      .toString()
      .replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    const tail = places
      ? (rounded % scale).toString().padStart(places, "0").replace(/0+$/, "")
      : "";
    return (
      (negative && rounded !== 0n ? "-" : "") + whole + (tail ? "," + tail : "")
    );
  }
  const api = {
    maxIntegerDigits: MAX_INTEGER_DIGITS,
    maxResponseBytes: 64 * 1024 * 1024,
    NumericFormatError,
    formatDecimal,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.GridNumbers = api;
})(typeof window !== "undefined" ? window : globalThis);
