import ts from "typescript";

const DOMAIN_CLAIM = /\b(?:nessun\w*|mai|assente|presente|non salvata)\b/i;

function authoritativeEffectStateViolations(source: string, relativePath: string) {
  const file = ts.createSourceFile(
    relativePath,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const violations: string[] = [];

  function visit(node: ts.Node) {
    const manualEffects = ts.isFunctionLike(node)
      ? manualAsyncEffects(node, file)
      : [];
    if (
      ts.isFunctionLike(node)
      && manualEffects.length > 0
      && hasDomainClaim(node, file)
      && (
        !declaresAuthoritativeSnapshot(node, file)
        || (hasEffectDependencies(manualEffects) && !declaresTargetOwnership(node, file))
      )
    ) {
      const position = file.getLineAndCharacterOfPosition(node.getStart(file));
      violations.push(`${relativePath}:${position.line + 1}:${position.character + 1}`);
      return;
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return violations;
}

function manualAsyncEffects(node: ts.SignatureDeclaration, file: ts.SourceFile) {
  const effects: ts.CallExpression[] = [];
  const visit = (candidate: ts.Node) => {
    if (
      ts.isCallExpression(candidate)
      && candidate.expression.getText(file) === "useEffect"
      && candidate.arguments[0]
    ) {
      const effectText = candidate.arguments[0].getText(file);
      if (effectText.includes(".then(") && effectText.includes(".catch(")) effects.push(candidate);
    }
    if (candidate !== node && ts.isFunctionLike(candidate)) return;
    ts.forEachChild(candidate, visit);
  };
  ts.forEachChild(node, visit);
  return effects;
}

function hasEffectDependencies(effects: ts.CallExpression[]) {
  return effects.some((effect) => {
    const dependencies = effect.arguments[1];
    return ts.isArrayLiteralExpression(dependencies)
      && dependencies.elements.length > 0;
  });
}

function hasDomainClaim(node: ts.SignatureDeclaration, file: ts.SourceFile) {
  let found = false;
  const visit = (candidate: ts.Node) => {
    if (
      (ts.isJsxText(candidate) || ts.isStringLiteral(candidate))
      && DOMAIN_CLAIM.test(candidate.getText(file))
    ) found = true;
    if (!found && candidate !== node && ts.isFunctionLike(candidate)) return;
    if (!found) ts.forEachChild(candidate, visit);
  };
  ts.forEachChild(node, visit);
  return found;
}

function declaresAuthoritativeSnapshot(node: ts.SignatureDeclaration, file: ts.SourceFile) {
  let found = false;
  const visit = (candidate: ts.Node) => {
    if (
      ts.isTypeReferenceNode(candidate)
      && candidate.typeName.getText(file) === "AuthoritativeSnapshot"
    ) found = true;
    if (!found && candidate !== node && ts.isFunctionLike(candidate)) return;
    if (!found) ts.forEachChild(candidate, visit);
  };
  ts.forEachChild(node, visit);
  return found;
}

function declaresTargetOwnership(node: ts.SignatureDeclaration, file: ts.SourceFile) {
  let ownsSnapshot = false;
  let fencesPresentation = false;
  const visit = (candidate: ts.Node) => {
    if (
      (ts.isPropertySignature(candidate) || ts.isPropertyAssignment(candidate))
      && candidate.name.getText(file) === "targetKey"
    ) ownsSnapshot = true;
    if (
      ts.isBinaryExpression(candidate)
      && candidate.operatorToken.kind === ts.SyntaxKind.EqualsEqualsEqualsToken
      && (
        isTargetKeyAccess(candidate.left, file)
        || isTargetKeyAccess(candidate.right, file)
      )
    ) fencesPresentation = true;
    if (candidate !== node && ts.isFunctionLike(candidate)) return;
    ts.forEachChild(candidate, visit);
  };
  ts.forEachChild(node, visit);
  return ownsSnapshot && fencesPresentation;
}

function isTargetKeyAccess(node: ts.Expression, file: ts.SourceFile) {
  return ts.isPropertyAccessExpression(node)
    && node.name.getText(file) === "targetKey";
}

export { authoritativeEffectStateViolations };
