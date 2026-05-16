package sample;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CalcTest {
    private final Calc calc = new Calc();

    @Test
    void testAdd() {
        assertEquals(5, calc.add(2, 3));
    }

    @Test
    void testIsEven() {
        assertTrue(calc.isEven(4));
        assertFalse(calc.isEven(7));
    }

    @Test
    void testForceFailable() {
        // -DforceFail=true 让此用例失败，用于 Spike-2 Red 验收
        if ("true".equals(System.getProperty("forceFail"))) {
            fail("forced failure via -DforceFail=true (Spike-2 Red 验收)");
        }
    }
}
