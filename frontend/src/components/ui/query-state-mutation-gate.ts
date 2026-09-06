import ts from "typescript";

type MutationDecisionAnalysis = {
  booleanFallbackRoots: (identifier: ts.Identifier, use: ts.Node) => Set<string>;
  file: ts.SourceFile;
  snapshotRoots: (node: ts.Node, use: ts.Node) => Set<string>;
};

function isMutationCall(node: ts.CallExpression) {
  return ts.isPropertyAccessExpression(node.expression)
    && /^(?:mutate|mutateAsync)$/.test(node.expression.name.text);
}

function mutationDecisionSnapshotRoots(
  call: ts.CallExpression,
  analysis: MutationDecisionAnalysis,
) {
  const roots = new Set<string>();
  const visit = (node: ts.Node) => {
    if (ts.isIdentifier(node) && isValueIdentifier(node)) {
      addAll(roots, analysis.booleanFallbackRoots(node, call));
    }
    if (ts.isConditionalExpression(node)) {
      addAll(roots, analysis.snapshotRoots(node.condition, call));
    } else if (
      ts.isCallExpression(node)
      && node.expression.getText(analysis.file) === "Boolean"
      && node.arguments[0]
    ) {
      addAll(roots, analysis.snapshotRoots(node.arguments[0], call));
    } else if (
      ts.isPrefixUnaryExpression(node)
      && node.operator === ts.SyntaxKind.ExclamationToken
    ) {
      addAll(roots, analysis.snapshotRoots(node.operand, call));
    } else if (
      ts.isBinaryExpression(node)
      && isFallbackOperator(node.operatorToken.kind)
      && isBooleanLiteral(node.right)
    ) {
      addAll(roots, analysis.snapshotRoots(node.left, call));
    }
    if (node !== call && ts.isFunctionLike(node)) return;
    ts.forEachChild(node, visit);
  };
  for (const argument of call.arguments) visit(argument);
  return roots;
}

function isValueIdentifier(identifier: ts.Identifier) {
  const parent = identifier.parent;
  if (ts.isPropertyAccessExpression(parent) && parent.name === identifier) return false;
  if (ts.isPropertyAssignment(parent) && parent.name === identifier) return false;
  if (ts.isJsxAttribute(parent) && parent.name === identifier) return false;
  return true;
}

function isFallbackOperator(kind: ts.SyntaxKind) {
  return kind === ts.SyntaxKind.BarBarToken || kind === ts.SyntaxKind.QuestionQuestionToken;
}

function isBooleanLiteral(node: ts.Expression) {
  const expression = unwrapExpression(node);
  return expression.kind === ts.SyntaxKind.TrueKeyword
    || expression.kind === ts.SyntaxKind.FalseKeyword;
}

function unwrapExpression(expression: ts.Expression): ts.Expression {
  if (
    ts.isParenthesizedExpression(expression)
    || ts.isAsExpression(expression)
    || ts.isNonNullExpression(expression)
  ) return unwrapExpression(expression.expression);
  return expression;
}

function addAll(target: Set<string>, source: Set<string>) {
  for (const item of source) target.add(item);
}

export { isMutationCall, mutationDecisionSnapshotRoots };
