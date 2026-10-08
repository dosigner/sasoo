// The UI owns numbering. Leave decimals and section numbers intact.
export function stripRecipeStepNumber(step: string): string {
  return step.replace(/^\s*\d+[.)]\s+/, '');
}
