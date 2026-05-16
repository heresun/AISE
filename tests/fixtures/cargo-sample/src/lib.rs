//! Spike-3 fixture：最小可测函数 + 单元测试。
//! 设置环境变量 AISE_FIXTURE_FORCE_FAIL=1 让 test_force_failable 失败。

pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

pub fn is_even(n: i32) -> bool {
    n % 2 == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_add() {
        assert_eq!(add(2, 3), 5);
    }

    #[test]
    fn test_is_even() {
        assert!(is_even(4));
        assert!(!is_even(7));
    }

    #[test]
    fn test_force_failable() {
        if std::env::var("AISE_FIXTURE_FORCE_FAIL").as_deref() == Ok("1") {
            panic!("forced failure via AISE_FIXTURE_FORCE_FAIL=1 (Spike-3 Red 验收)");
        }
    }
}
