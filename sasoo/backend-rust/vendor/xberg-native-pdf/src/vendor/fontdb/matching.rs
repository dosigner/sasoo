// Derived from fontdb 0.24.0 (https://github.com/RazrFalcon/fontdb),
// Copyright (c) 2020 Yevhenii Reizner, MIT licensed. `find_best_match` is a
// near-verbatim port (upstream itself credits servo/font-kit) — this is pure
// CSS Fonts Level 4 combinatorics over Stretch/Style/Weight, unrelated to the
// ttf_parser/skrifa swap, so it is intentionally not rewritten. ~keep

//! CSS Fonts Module Level 4 §font-style-matching, used by `Database::query`.

use super::{FaceInfo, ID, Query, Stretch, Style, Weight};

/// Picks the best-matching candidate for `query` per the CSS Fonts Level 4
/// font-style-matching algorithm. `candidates` must be non-empty.
///
/// <https://www.w3.org/TR/2018/REC-css-fonts-3-20180920/#font-style-matching>
/// Based on <https://github.com/servo/font-kit>.
#[inline(never)]
pub(super) fn find_best_match(candidates: &[(ID, &FaceInfo)], query: &Query) -> Option<ID> {
    debug_assert!(!candidates.is_empty());

    // Step 4 of the font-style-matching algorithm linked above. ~keep
    let mut matching_set: Vec<usize> = (0..candidates.len()).collect();

    // Step 4a (`font-stretch`). ~keep
    let matches = matching_set
        .iter()
        .any(|&index| candidates[index].1.stretch == query.stretch);
    let matching_stretch = if matches {
        // Exact match. ~keep
        query.stretch
    } else if query.stretch <= Stretch::Normal {
        // Closest stretch, first checking narrower values and then wider values. ~keep
        let stretch = matching_set
            .iter()
            .filter(|&&index| candidates[index].1.stretch < query.stretch)
            .min_by_key(|&&index| query.stretch.to_number() - candidates[index].1.stretch.to_number());

        match stretch {
            Some(&matching_index) => candidates[matching_index].1.stretch,
            None => {
                let matching_index = *matching_set
                    .iter()
                    .min_by_key(|&&index| candidates[index].1.stretch.to_number() - query.stretch.to_number())?;

                candidates[matching_index].1.stretch
            }
        }
    } else {
        // Closest stretch, first checking wider values and then narrower values. ~keep
        let stretch = matching_set
            .iter()
            .filter(|&&index| candidates[index].1.stretch > query.stretch)
            .min_by_key(|&&index| candidates[index].1.stretch.to_number() - query.stretch.to_number());

        match stretch {
            Some(&matching_index) => candidates[matching_index].1.stretch,
            None => {
                let matching_index = *matching_set
                    .iter()
                    .min_by_key(|&&index| query.stretch.to_number() - candidates[index].1.stretch.to_number())?;

                candidates[matching_index].1.stretch
            }
        }
    };
    matching_set.retain(|&index| candidates[index].1.stretch == matching_stretch);

    // Step 4b (`font-style`). ~keep
    let style_preference = match query.style {
        Style::Italic => [Style::Italic, Style::Oblique, Style::Normal],
        Style::Oblique => [Style::Oblique, Style::Italic, Style::Normal],
        Style::Normal => [Style::Normal, Style::Oblique, Style::Italic],
    };
    let matching_style = *style_preference.iter().find(|&query_style| {
        matching_set
            .iter()
            .any(|&index| candidates[index].1.style == *query_style)
    })?;

    matching_set.retain(|&index| candidates[index].1.style == matching_style);

    // Step 4c (`font-weight`).
    //
    // The spec doesn't say what to do if the weight is between 400 and 500 exclusive, so we
    // just use 450 as the cutoff. ~keep
    let weight = query.weight.0;

    let matching_weight = if matching_set.iter().any(|&index| candidates[index].1.weight.0 == weight) {
        Weight(weight)
    } else if (400..450).contains(&weight) && matching_set.iter().any(|&index| candidates[index].1.weight.0 == 500) {
        // Check 500 first. ~keep
        Weight::MEDIUM
    } else if (450..=500).contains(&weight) && matching_set.iter().any(|&index| candidates[index].1.weight.0 == 400) {
        // Check 400 first. ~keep
        Weight::NORMAL
    } else if weight <= 500 {
        // Closest weight, first checking thinner values and then fatter ones. ~keep
        let idx = matching_set
            .iter()
            .filter(|&&index| candidates[index].1.weight.0 <= weight)
            .min_by_key(|&&index| weight - candidates[index].1.weight.0);

        match idx {
            Some(&matching_index) => candidates[matching_index].1.weight,
            None => {
                let matching_index = *matching_set
                    .iter()
                    .min_by_key(|&&index| candidates[index].1.weight.0 - weight)?;
                candidates[matching_index].1.weight
            }
        }
    } else {
        // Closest weight, first checking fatter values and then thinner ones. ~keep
        let idx = matching_set
            .iter()
            .filter(|&&index| candidates[index].1.weight.0 >= weight)
            .min_by_key(|&&index| candidates[index].1.weight.0 - weight);

        match idx {
            Some(&matching_index) => candidates[matching_index].1.weight,
            None => {
                let matching_index = *matching_set
                    .iter()
                    .min_by_key(|&&index| weight - candidates[index].1.weight.0)?;
                candidates[matching_index].1.weight
            }
        }
    };
    matching_set.retain(|&index| candidates[index].1.weight == matching_weight);

    // Ignore step 4d (`font-size`). ~keep

    // Return the result. ~keep
    matching_set.into_iter().next().map(|index| candidates[index].0)
}
