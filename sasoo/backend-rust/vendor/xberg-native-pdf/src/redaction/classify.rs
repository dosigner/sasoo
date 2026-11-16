//! CTM tracking for the redaction content-stream walk.
//!
//! A content stream is a sequence of operators drawn in *local* coordinate
//! systems nested by `q … cm … Q`. The redaction engine needs the composed
//! CTM to be correct at each mark, so it feeds every operator through
//! [`apply_ctm`] while iterating. The CTM stack machinery itself is reused
//! from [`crate::content::graphics_state`] rather than reimplemented.

use crate::content::graphics_state::{GraphicsStateStack, Matrix};
use crate::content::operators::Operator;

/// Update a [`GraphicsStateStack`]'s CTM for one operator.
///
/// Handles only the transformation-affecting operators (`q` → save,
/// `Q` → restore, `cm` → concat); every other operator leaves the CTM
/// unchanged. Pruners call this while iterating so the CTM is correct at
/// each mark. `Q` at the base stack is a safe no-op (malformed input must
/// not panic).
pub fn apply_ctm(stack: &mut GraphicsStateStack, op: &Operator) {
    match op {
        Operator::SaveState => stack.save(),
        Operator::RestoreState => stack.restore(),
        Operator::Cm { a, b, c, d, e, f } => {
            let m = Matrix {
                a: *a,
                b: *b,
                c: *c,
                d: *d,
                e: *e,
                f: *f,
            };
            // PDF `cm` pre-concatenates: CTM' = M × CTM_old. This
            // codebase's `Matrix::multiply(self, other)` applies `self`
            // first then `other` (row-vector p·self·other); the
            // established convention is `cm_matrix.multiply(&old_ctm)`
            // (mirrors src/content/parser.rs:687). ~keep
            let old = stack.current().ctm;
            stack.current_mut().ctm = m.multiply(&old);
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn apply_ctm_nested_concatenation_order() {
        // `cm translate(100,0)` then `cm scale(2,2)`: a local point (5,5)
        // must map scale-first then translate → (110,10). ~keep
        let mut stack = GraphicsStateStack::new();
        apply_ctm(
            &mut stack,
            &Operator::Cm {
                a: 1.0,
                b: 0.0,
                c: 0.0,
                d: 1.0,
                e: 100.0,
                f: 0.0,
            },
        );
        apply_ctm(
            &mut stack,
            &Operator::Cm {
                a: 2.0,
                b: 0.0,
                c: 0.0,
                d: 2.0,
                e: 0.0,
                f: 0.0,
            },
        );
        let p = stack.current().ctm.transform_point(5.0, 5.0);
        assert!((p.x - 110.0).abs() < 1e-4 && (p.y - 10.0).abs() < 1e-4);
    }

    #[test]
    fn apply_ctm_restore_at_base_is_safe_noop() {
        // Malformed: unbalanced Q must not panic and must not corrupt CTM. ~keep
        let mut stack = GraphicsStateStack::new();
        let d0 = stack.depth();
        apply_ctm(&mut stack, &Operator::RestoreState);
        apply_ctm(&mut stack, &Operator::RestoreState);
        assert_eq!(stack.depth(), d0);
        let c = stack.current().ctm;
        assert!((c.a - 1.0).abs() < 1e-6 && (c.d - 1.0).abs() < 1e-6);
    }
}
