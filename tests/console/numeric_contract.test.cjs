"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {
  formatDecimal,
  maxIntegerDigits,
} = require("../../research_console/static/lab.js");
const {
  temporalContext,
  samplingGap,
} = require("../../research_console/static/charts.js");

test("derived fractions beyond both old limits keep exact half-even display", () => {
  for (const digits of [311, 4442, 46000]) {
    const denominator = 10n ** BigInt(digits) + 7n;
    assert.equal(formatDecimal(`${denominator - 1n}/${denominator}`, 6), "1");
    assert.equal(
      formatDecimal(`${denominator * 201n}/${denominator * 200n}`, 2),
      "1",
    );
    assert.equal(
      formatDecimal(`${denominator * 203n}/${denominator * 200n}`, 2),
      "1,02",
    );
  }
});
test("tiny nonzero and huge values are bounded explicit approximations, not exact zero", () => {
  assert.equal(formatDecimal("0", 2), "0");
  assert.equal(formatDecimal("1e-100", 8), "≈ 1e-100");
  assert.equal(formatDecimal("-1e-100", 8), "≈ -1e-100");
  assert.equal(formatDecimal("1e120", 8), "≈ 1e+120");
  assert.equal(formatDecimal("1" + "0".repeat(5001), 8), "≈ 1e+5001");
  assert.equal(formatDecimal("1/" + "1" + "0".repeat(5001), 8), "≈ 1e-5001");
  assert.equal(
    formatDecimal("9007199254740993.01", 2),
    "9.007.199.254.740.993,01",
  );
  assert.equal(formatDecimal("-0.0025", 2, 100), "-0,25");
  assert.throws(() => formatDecimal("1", 2, 0));
});
test("numeric lengths are checked before BigInt; bad syntax never becomes zero", () => {
  assert.equal(maxIntegerDigits, 4_000_016);
  for (const value of [
    "1/0",
    "1/-2",
    "1/2/3",
    "NaN",
    "Infinity",
    "<svg>",
    "١/٢",
    "1e999",
    "1".repeat(maxIntegerDigits + 1) + "/1",
  ])
    assert.throws(() => formatDecimal(value));
  assert.throws(() => formatDecimal("1", 13));
});
const account = (times) => ({ series: times.map((time) => ({ time })) });
const t = (minute) => new Date(Date.UTC(2020, 0, 1, 0, minute)).toISOString();
test("PAPER minute timestamps produce an observed 60 second label", () => {
  const c = temporalContext([account([t(0), t(1), t(2), t(3)])], {});
  assert.equal(c.sampling_seconds, 60);
  assert.match(c.cadence_note, /observada.*60 segundos/);
  assert.doesNotMatch(c.cadence_note, /86400/);
  assert.equal(samplingGap(t(0), t(1), c), false);
});
test("explicit daily cadence remains declared and censors shorter and longer gaps", () => {
  const c = temporalContext([account([t(0), t(1440), t(2880)])], {
    sampling_seconds: 86400,
  });
  assert.equal(c.sampling_seconds, 86400);
  assert.match(c.cadence_note, /declarada: 86400 segundos/);
  assert.equal(samplingGap(t(0), t(1), c), true);
  assert.equal(samplingGap(t(0), t(1440), c), false);
});
test("irregular, duplicate, single and absent times never invent fixed cadence", () => {
  for (const values of [
    [t(0), t(1), t(3)],
    [t(0), t(0)],
    [t(0)],
    [],
    ["not-time", t(1)],
  ]) {
    const c = temporalContext([account(values)], {});
    assert.equal(c.sampling_seconds, null);
    assert.match(c.cadence_note, /cadência fixa não demonstrada/);
  }
});
test("timezone representation does not turn elapsed minutes into event indexes", () => {
  const c = temporalContext(
    [account(["2020-01-01T01:00:00+01:00", "2020-01-01T00:01:00Z"])],
    {},
  );
  assert.equal(c.sampling_seconds, 60);
});
