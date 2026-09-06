import ts from "typescript";

import {
  isMutationCall,
  mutationDecisionSnapshotRoots,
} from "@/components/ui/query-state-mutation-gate";

type Binding = {
  declaration: ts.Identifier;
  initializer?: ts.Expression;
  scope: ts.Node;
};

type Analysis = {
  bindings: Binding[];
  dependencies: Map<Binding, Set<string>>;
  fallbacks: Map<Binding, Set<FallbackKind>>;
  file: ts.SourceFile;
};

type FallbackKind = "zero" | "collection" | "boolean";

const EMPTY_CLAIM = /\b(?:nessun\w*|vuot\w*)\b/i;

export function queryStateFallbackViolations(source: string, relativePath: string) {
  const file = ts.createSourceFile(
    relativePath,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const analysis = analyzeBindings(file);
  const violations: string[] = [];

  function record(node: ts.Node, roots: Set<string>) {
    for (const root of roots) {
      if (!claimHasSnapshotGuard(node, root, analysis)) {
        const position = file.getLineAndCharacterOfPosition(node.getStart(file));
        violations.push(`${relativePath}:${position.line + 1}:${position.character + 1} ${root}`);
      }
    }
  }

  function visit(node: ts.Node) {
    if (isEmptyClaim(node)) {
      record(node, controllingSnapshotRoots(node, analysis));
    }
    if (ts.isJsxExpression(node) && node.expression) {
      record(node, fallbackSnapshotRoots(node.expression, node, analysis));
    }
    if (ts.isCallExpression(node) && isMutationCall(node)) {
      record(node, mutationDecisionSnapshotRoots(node, {
        booleanFallbackRoots: (identifier, use) => {
          const binding = resolveBinding(identifier, use, analysis);
          return binding && analysis.fallbacks.get(binding)?.has("boolean")
            ? analysis.dependencies.get(binding) || new Set()
            : new Set();
        },
        file,
        snapshotRoots: (candidate, use) => snapshotRoots(candidate, use, analysis),
      }));
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return [...new Set(violations)];
}

function analyzeBindings(file: ts.SourceFile): Analysis {
  const bindings: Binding[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
      bindings.push({
        declaration: node.name,
        initializer: node.initializer,
        scope: bindingScope(node),
      });
    } else if (ts.isParameter(node) && ts.isIdentifier(node.name)) {
      bindings.push({ declaration: node.name, scope: bindingScope(node) });
    }
    ts.forEachChild(node, visit);
  };
  visit(file);

  const analysis: Analysis = {
    bindings,
    dependencies: new Map(),
    fallbacks: new Map(),
    file,
  };
  let changed = true;
  while (changed) {
    changed = false;
    for (const binding of bindings) {
      if (!binding.initializer) continue;
      const roots = snapshotRoots(binding.initializer, binding.initializer, analysis);
      const previous = analysis.dependencies.get(binding) || new Set<string>();
      const next = new Set([...previous, ...roots]);
      if (next.size !== previous.size) {
        analysis.dependencies.set(binding, next);
        changed = true;
      }
      const previousFallbacks = analysis.fallbacks.get(binding) || new Set<FallbackKind>();
      const nextFallbacks = new Set([
        ...previousFallbacks,
        ...fallbackKinds(binding.initializer, binding.initializer, analysis),
      ]);
      if (nextFallbacks.size !== previousFallbacks.size) {
        analysis.fallbacks.set(binding, nextFallbacks);
        changed = true;
      }
    }
  }
  return analysis;
}

function bindingScope(node: ts.Node): ts.Node {
  for (let current = node.parent; current; current = current.parent) {
    if (ts.isFunctionLike(current) || ts.isSourceFile(current) || ts.isBlock(current)) {
      return current;
    }
  }
  return node.getSourceFile();
}

function resolveBinding(identifier: ts.Identifier, use: ts.Node, analysis: Analysis) {
  const candidates = analysis.bindings.filter(
    (binding) =>
      binding.declaration.text === identifier.text
      && containsNode(binding.scope, use)
      && (ts.isParameter(binding.declaration.parent)
        || binding.declaration.getStart(analysis.file) <= use.getStart(analysis.file)),
  );
  return candidates.sort((left, right) => {
    const leftSpan = left.scope.end - left.scope.pos;
    const rightSpan = right.scope.end - right.scope.pos;
    return leftSpan - rightSpan
      || right.declaration.getStart(analysis.file) - left.declaration.getStart(analysis.file);
  })[0];
}

function snapshotRoots(node: ts.Node, use: ts.Node, analysis: Analysis) {
  const roots = new Set<string>();
  const visit = (candidate: ts.Node) => {
    const text = candidate.getText(analysis.file);
    const match = text.match(
      /^([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\.(data|snapshot)(?:\?|\.|$)/,
    );
    if (match) roots.add(`${match[1]}.${match[2]}`);
    if (ts.isIdentifier(candidate) && isValueIdentifier(candidate)) {
      const binding = resolveBinding(candidate, use, analysis);
      for (const root of binding ? analysis.dependencies.get(binding) || [] : []) {
        roots.add(root);
      }
    }
    ts.forEachChild(candidate, visit);
  };
  visit(node);
  return roots;
}

function isEmptyClaim(node: ts.Node) {
  if (ts.isJsxText(node)) return EMPTY_CLAIM.test(node.text);
  return ts.isStringLiteral(node) && isInsideJsx(node) && EMPTY_CLAIM.test(node.text);
}

function isInsideJsx(node: ts.Node) {
  for (let current = node.parent; current; current = current.parent) {
    if (ts.isJsxElement(current) || ts.isJsxFragment(current)) return true;
    if (ts.isFunctionLike(current)) return false;
  }
  return false;
}

function controllingSnapshotRoots(node: ts.Node, analysis: Analysis) {
  const roots = new Set<string>();
  for (let current = node.parent; current; current = current.parent) {
    if (ts.isConditionalExpression(current)) {
      addAll(roots, snapshotRoots(current.condition, current.condition, analysis));
    } else if (
      ts.isBinaryExpression(current)
      && current.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken
    ) {
      addAll(roots, snapshotRoots(current.left, current.left, analysis));
    }
    if (ts.isReturnStatement(current) || ts.isFunctionLike(current)) break;
  }
  return roots;
}

function fallbackSnapshotRoots(
  expression: ts.Expression,
  use: ts.Node,
  analysis: Analysis,
) {
  const roots = new Set<string>();
  const allowedKinds = jsxFallbackKinds(use);
  if (!allowedKinds.size) return roots;
  const visit = (candidate: ts.Node) => {
    if (
      candidate !== expression
      && (ts.isJsxElement(candidate)
        || ts.isJsxSelfClosingElement(candidate)
        || ts.isJsxFragment(candidate))
    ) return;
    if (ts.isIdentifier(candidate) && isValueIdentifier(candidate)) {
      const binding = resolveBinding(candidate, use, analysis);
      if (
        binding
        && [...(analysis.fallbacks.get(binding) || [])].some((kind) => allowedKinds.has(kind))
      ) {
        addAll(roots, analysis.dependencies.get(binding) || new Set());
      }
    }
    if ([...directFallbackKinds(candidate)].some((kind) => allowedKinds.has(kind))) {
      addAll(roots, directFallbackRoots(candidate, use, analysis));
    }
    ts.forEachChild(candidate, visit);
  };
  visit(expression);
  return roots;
}

function fallbackKinds(
  expression: ts.Expression,
  use: ts.Node,
  analysis: Analysis,
) {
  const kinds = new Set<FallbackKind>();
  const unwrapped = unwrapExpression(expression);
  if (ts.isIdentifier(unwrapped)) {
    const binding = resolveBinding(unwrapped, use, analysis);
    for (const kind of binding ? analysis.fallbacks.get(binding) || [] : []) {
      kinds.add(kind);
    }
    return kinds;
  }
  const visit = (candidate: ts.Node) => {
    for (const kind of directFallbackKinds(candidate)) {
      if (snapshotRoots(candidate, use, analysis).size) kinds.add(kind);
    }
    if (candidate !== expression && ts.isFunctionLike(candidate)) return;
    ts.forEachChild(candidate, visit);
  };
  visit(expression);
  return kinds;
}

function jsxFallbackKinds(use: ts.Node) {
  if (!ts.isJsxAttribute(use.parent)) return new Set<FallbackKind>(["zero"]);
  const name = use.parent.name.getText(use.getSourceFile());
  if (/^(?:disabled|checked|selected|className|key|aria-|on[A-Z])/.test(name)) {
    return new Set<FallbackKind>();
  }
  return new Set<FallbackKind>(["zero", "collection"]);
}

function isFallbackOperator(kind: ts.SyntaxKind) {
  return kind === ts.SyntaxKind.BarBarToken || kind === ts.SyntaxKind.QuestionQuestionToken;
}

function fallbackLiteralKind(node: ts.Expression): FallbackKind | undefined {
  const expression = unwrapExpression(node);
  if (expression.kind === ts.SyntaxKind.TrueKeyword || expression.kind === ts.SyntaxKind.FalseKeyword) {
    return "boolean";
  }
  if (ts.isNumericLiteral(expression) && Number(expression.text) === 0) return "zero";
  if (
    (ts.isArrayLiteralExpression(expression) && expression.elements.length === 0)
    || (ts.isObjectLiteralExpression(expression) && expression.properties.length === 0)
  ) return "collection";
  return undefined;
}

function directFallbackKinds(node: ts.Node) {
  const kinds = new Set<FallbackKind>();
  if (
    ts.isBinaryExpression(node)
    && isFallbackOperator(node.operatorToken.kind)
  ) {
    const kind = fallbackLiteralKind(node.right);
    if (kind) kinds.add(kind);
  }
  if (ts.isConditionalExpression(node)) {
    const trueKind = fallbackLiteralKind(node.whenTrue);
    const falseKind = fallbackLiteralKind(node.whenFalse);
    if (trueKind) kinds.add(trueKind);
    if (falseKind) kinds.add(falseKind);
  }
  if (
    ts.isCallExpression(node)
    && node.expression.getText(node.getSourceFile()) === "Boolean"
  ) kinds.add("boolean");
  if (
    ts.isPrefixUnaryExpression(node)
    && node.operator === ts.SyntaxKind.ExclamationToken
  ) kinds.add("boolean");
  return kinds;
}

function directFallbackRoots(node: ts.Node, use: ts.Node, analysis: Analysis) {
  const roots = new Set<string>();
  if (ts.isBinaryExpression(node)) {
    addAll(roots, snapshotRoots(node.left, use, analysis));
  } else if (ts.isConditionalExpression(node)) {
    addAll(roots, snapshotRoots(node.condition, use, analysis));
    if (!fallbackLiteralKind(node.whenTrue)) {
      addAll(roots, snapshotRoots(node.whenTrue, use, analysis));
    }
    if (!fallbackLiteralKind(node.whenFalse)) {
      addAll(roots, snapshotRoots(node.whenFalse, use, analysis));
    }
  }
  return roots;
}

function isValueIdentifier(identifier: ts.Identifier) {
  const parent = identifier.parent;
  if (ts.isPropertyAccessExpression(parent) && parent.name === identifier) return false;
  if (ts.isPropertyAssignment(parent) && parent.name === identifier) return false;
  if (ts.isShorthandPropertyAssignment(parent)) return true;
  if (ts.isJsxAttribute(parent) && parent.name === identifier) return false;
  return true;
}

function claimHasSnapshotGuard(node: ts.Node, root: string, analysis: Analysis) {
  for (let current = node.parent; current; current = current.parent) {
    if (ts.isJsxElement(current) && jsxBoundaryGuardsRoot(current, root, analysis)) {
      return true;
    }
    if (
      (ts.isJsxSelfClosingElement(current) || ts.isJsxOpeningElement(current))
      && jsxAttributesGuardRoot(current.attributes, root, analysis)
    ) {
      return true;
    }
    if (ts.isConditionalExpression(current)) {
      const inTrueBranch = containsNode(current.whenTrue, node);
      const inFalseBranch = containsNode(current.whenFalse, node);
      if (
        (inTrueBranch && expressionGuaranteesRoot(current.condition, root, true, analysis))
        || (inFalseBranch && expressionGuaranteesRoot(current.condition, root, false, analysis))
      ) return true;
    }
    if (
      ts.isBinaryExpression(current)
      && current.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken
      && containsNode(current.right, node)
      && expressionGuaranteesRoot(current.left, root, true, analysis)
    ) return true;
    if (ts.isReturnStatement(current)) {
      return precedingEarlyReturnGuardsRoot(current, root, analysis);
    }
    if (
      ts.isBlock(current)
      && precedingStatementsGuardNode(current, node, root, analysis)
    ) return true;
    if (ts.isFunctionLike(current)) break;
  }
  return false;
}

function precedingStatementsGuardNode(
  block: ts.Block,
  node: ts.Node,
  root: string,
  analysis: Analysis,
) {
  const index = block.statements.findIndex((statement) => containsNode(statement, node));
  if (index < 0) return false;
  return block.statements.slice(0, index).some((statement) =>
    ts.isIfStatement(statement)
    && statementReturns(statement.thenStatement)
    && expressionGuaranteesRoot(statement.expression, root, false, analysis),
  );
}

function jsxBoundaryGuardsRoot(element: ts.JsxElement, root: string, analysis: Analysis) {
  return element.openingElement.tagName.getText(analysis.file) === "QueryStateBoundary"
    && jsxAttributesGuardRoot(element.openingElement.attributes, root, analysis);
}

function jsxAttributesGuardRoot(
  attributes: ts.JsxAttributes,
  root: string,
  analysis: Analysis,
) {
  return attributes.properties.some((property) => {
    if (
      !ts.isJsxAttribute(property)
      || !/^(?:hasData|ready|\w+Ready|\w+Loaded)$/.test(
        property.name.getText(analysis.file),
      )
    ) return false;
    const expression = property.initializer && ts.isJsxExpression(property.initializer)
      ? property.initializer.expression
      : undefined;
    return Boolean(
      expression
      && (expressionGuaranteesRoot(expression, root, true, analysis)
        || expressionMentionsRootReadiness(expression, root, analysis)),
    );
  });
}

function expressionMentionsRootReadiness(
  expression: ts.Expression,
  root: string,
  analysis: Analysis,
) {
  const readiness = root.replace(/\.(?:data|snapshot)$/, ".hasData");
  let found = false;
  const visit = (node: ts.Node) => {
    if (node.getText(analysis.file) === readiness) found = true;
    if (!found) ts.forEachChild(node, visit);
  };
  visit(expression);
  return found;
}

function expressionGuaranteesRoot(
  expression: ts.Expression,
  root: string,
  branchWhenTrue: boolean,
  analysis: Analysis,
): boolean {
  const unwrapped = unwrapExpression(expression);
  if (ts.isIdentifier(unwrapped)) {
    const binding = resolveBinding(unwrapped, unwrapped, analysis);
    if (binding?.initializer) {
      return expressionGuaranteesRoot(binding.initializer, root, branchWhenTrue, analysis);
    }
  }
  if (ts.isPrefixUnaryExpression(unwrapped) && unwrapped.operator === ts.SyntaxKind.ExclamationToken) {
    return expressionGuaranteesRoot(unwrapped.operand, root, !branchWhenTrue, analysis);
  }
  if (ts.isCallExpression(unwrapped) && unwrapped.expression.getText(analysis.file) === "Boolean") {
    const argument = unwrapped.arguments[0];
    return Boolean(argument && expressionGuaranteesRoot(argument, root, true, analysis))
      === branchWhenTrue;
  }
  if (ts.isBinaryExpression(unwrapped)) {
    const operator = unwrapped.operatorToken.kind;
    if (operator === ts.SyntaxKind.AmpersandAmpersandToken && branchWhenTrue) {
      return expressionGuaranteesRoot(unwrapped.left, root, true, analysis)
        || expressionGuaranteesRoot(unwrapped.right, root, true, analysis);
    }
    if (operator === ts.SyntaxKind.BarBarToken && !branchWhenTrue) {
      return expressionGuaranteesRoot(unwrapped.left, root, false, analysis)
        || expressionGuaranteesRoot(unwrapped.right, root, false, analysis);
    }
    if (isEqualityOperator(operator)) {
      const leftIsRoot = expressionReferencesOnlyRoot(unwrapped.left, root, analysis);
      const rightNullish = /^(?:null|undefined)$/.test(unwrapped.right.getText(analysis.file));
      if (leftIsRoot && rightNullish) {
        const inequality = operator === ts.SyntaxKind.ExclamationEqualsToken
          || operator === ts.SyntaxKind.ExclamationEqualsEqualsToken;
        return branchWhenTrue === inequality;
      }
    }
  }
  return expressionReferencesOnlyRoot(unwrapped, root, analysis) && branchWhenTrue;
}

function isEqualityOperator(kind: ts.SyntaxKind) {
  return [
    ts.SyntaxKind.ExclamationEqualsToken,
    ts.SyntaxKind.ExclamationEqualsEqualsToken,
    ts.SyntaxKind.EqualsEqualsToken,
    ts.SyntaxKind.EqualsEqualsEqualsToken,
  ].includes(kind);
}

function expressionReferencesOnlyRoot(
  expression: ts.Node,
  root: string,
  analysis: Analysis,
) {
  const text = expression.getText(analysis.file);
  if (text === root) return true;
  if (text === root.replace(/\.(?:data|snapshot)$/, ".hasData")) return true;
  if (!ts.isIdentifier(expression)) return false;
  const binding = resolveBinding(expression, expression, analysis);
  const roots = binding ? analysis.dependencies.get(binding) : undefined;
  return roots?.size === 1 && roots.has(root);
}

function unwrapExpression(expression: ts.Expression): ts.Expression {
  if (
    ts.isParenthesizedExpression(expression)
    || ts.isAsExpression(expression)
    || ts.isNonNullExpression(expression)
  ) return unwrapExpression(expression.expression);
  return expression;
}

function precedingEarlyReturnGuardsRoot(
  returnStatement: ts.ReturnStatement,
  root: string,
  analysis: Analysis,
) {
  const block = returnStatement.parent;
  if (!ts.isBlock(block)) return false;
  const index = block.statements.indexOf(returnStatement);
  return block.statements.slice(0, index).some((statement) =>
    ts.isIfStatement(statement)
    && statementReturns(statement.thenStatement)
    && expressionGuaranteesRoot(statement.expression, root, false, analysis),
  );
}

function statementReturns(statement: ts.Statement): boolean {
  if (ts.isReturnStatement(statement)) return true;
  return ts.isBlock(statement) && statement.statements.some(ts.isReturnStatement);
}

function containsNode(container: ts.Node, candidate: ts.Node) {
  return candidate.pos >= container.pos && candidate.end <= container.end;
}

function addAll(target: Set<string>, source: Set<string>) {
  for (const item of source) target.add(item);
}
