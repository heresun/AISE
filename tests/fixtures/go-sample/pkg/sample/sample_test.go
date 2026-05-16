// Spike-1 fixture：含通过 + （受环境变量控制的）失败用例。
// 设置 AISE_FIXTURE_FORCE_FAIL=1 让 TestForceFailable 失败，模拟 Red 状态。
package sample

import (
	"os"
	"testing"
)

func TestAdd(t *testing.T) {
	got := Add(2, 3)
	if got != 5 {
		t.Fatalf("Add(2,3) = %d; want 5", got)
	}
}

func TestIsEven(t *testing.T) {
	if !IsEven(4) {
		t.Fatal("IsEven(4) should be true")
	}
	if IsEven(7) {
		t.Fatal("IsEven(7) should be false")
	}
}

func TestForceFailable(t *testing.T) {
	if os.Getenv("AISE_FIXTURE_FORCE_FAIL") == "1" {
		t.Fatal("forced failure via AISE_FIXTURE_FORCE_FAIL=1 (Spike-1 Red 验收)")
	}
}
