// Spike-3 fixture：Jest 测试用例（含 PASS + 可控 FAIL）。
// AISE_FIXTURE_FORCE_FAIL=1 让 forceFailable 失败，模拟 Red 状态。
const { add, isEven } = require('./calc');

describe('calc', () => {
  test('add', () => {
    expect(add(2, 3)).toBe(5);
  });

  test('isEven', () => {
    expect(isEven(4)).toBe(true);
    expect(isEven(7)).toBe(false);
  });

  test('forceFailable', () => {
    if (process.env.AISE_FIXTURE_FORCE_FAIL === '1') {
      throw new Error('forced failure via AISE_FIXTURE_FORCE_FAIL=1 (Spike-3 Red 验收)');
    }
  });
});
