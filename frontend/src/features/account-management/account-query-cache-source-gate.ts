import ts from "typescript";

function accountQueryOwnershipViolations(source: string, relativePath: string) {
  const file = ts.createSourceFile(
    relativePath,
    source,
    ts.ScriptTarget.Latest,
    true,
    relativePath.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const violations: string[] = [];

  function visit(node: ts.Node) {
    if (
      ts.isCallExpression(node)
      && node.expression.getText(file) === "useQuery"
      && node.arguments[0]
      && ts.isObjectLiteralExpression(node.arguments[0])
    ) {
      const queryKey = node.arguments[0].properties.find(
        (property): property is ts.PropertyAssignment =>
          ts.isPropertyAssignment(property)
          && property.name.getText(file) === "queryKey",
      );
      if (!queryKey || !queryKey.initializer.getText(file).startsWith("accountQueryKeys.")) {
        const position = file.getLineAndCharacterOfPosition(node.getStart(file));
        violations.push(`${relativePath}:${position.line + 1}:${position.character + 1}`);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return violations;
}

export { accountQueryOwnershipViolations };
