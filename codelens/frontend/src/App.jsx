import { useEffect, useRef, useState } from 'react'
import './App.css'

const stages = [
  { id: 'lex', number: '01', name: 'Lexical analysis', shortName: 'Tokens' },
  { id: 'parse', number: '02', name: 'Syntax analysis', shortName: 'AST' },
  { id: 'semantic', number: '03', name: 'Semantic analysis', shortName: 'Symbols' },
  { id: 'translate', number: '04', name: 'Translation', shortName: 'Code' },
  { id: 'validate', number: '05', name: 'Validation', shortName: 'Check' },
]

const starterCode = `# A tiny program to explore
def double(value):
    return value * 2

answer = double(21)
print(answer)`

const featureMatrix = [
  { name: 'Numbers, arithmetic, comparisons', java: ['supported', 'Scalar numeric expressions'], cpp: ['supported', 'Scalar numeric expressions'], c: ['supported', 'Scalar numeric expressions'] },
  { name: 'if / elif / else', java: ['supported', ''], cpp: ['supported', ''], c: ['supported', ''] },
  { name: 'for-range and while loops', java: ['supported', ''], cpp: ['supported', ''], c: ['supported', ''] },
  { name: 'Functions and positional calls', java: ['supported', ''], cpp: ['supported', ''], c: ['supported', ''] },
  { name: 'Named parameter annotations', java: ['partial', 'Simple built-in and class-name annotations only'], cpp: ['unsupported', 'Annotated functions are not implemented'], c: ['unsupported', 'Annotated functions are not implemented'] },
  { name: 'Strings: index and iterate', java: ['supported', ''], cpp: ['partial', 'Narrow string operations supported by the native backend'], c: ['partial', 'Narrow string operations supported by the native backend'] },
  { name: 'String slices and common methods', java: ['partial', 'Includes split, join and clamped positive-step slices'], cpp: ['unsupported', 'String slices and method calls are not implemented'], c: ['unsupported', 'String slices and method calls are not implemented'] },
  { name: 'Lists / arrays: literals and indexing', java: ['supported', ''], cpp: ['partial', 'Integer-vector subset'], c: ['partial', 'Integer-array subset'] },
  { name: 'Two-value tuple return / unpacking', java: ['partial', 'Two-item tuples only'], cpp: ['partial', 'Two-item tuples only'], c: ['partial', 'Two-item tuples only'] },
  { name: 'Dictionaries', java: ['supported', ''], cpp: ['unsupported', 'Dictionary translation is not implemented'], c: ['unsupported', 'Dictionary translation is not implemented'] },
  { name: 'Classes and f-strings', java: ['partial', 'Simple top-level classes; basic interpolation and fixed-point formats'], cpp: ['unsupported', 'Classes and f-strings are not implemented'], c: ['unsupported', 'Classes and f-strings are not implemented'] },
  { name: 'Exceptions, dictionary item loops and sorting', java: ['partial', 'Exception-only try/except; dictionary items and value-key sorting subset'], cpp: ['unsupported', 'Not implemented by the native backend'], c: ['unsupported', 'Not implemented by the native backend'] },
  { name: 'Default / variadic function arguments', java: ['partial', 'Defaults are supported; variadic arguments are not'], cpp: ['unsupported', 'Default and variadic arguments are not implemented'], c: ['unsupported', 'Default and variadic arguments are not implemented'] },
  { name: 'List comprehensions', java: ['partial', 'One unfiltered generator; dictionary .items() supported'], cpp: ['unsupported', 'List comprehensions are not implemented'], c: ['unsupported', 'List comprehensions are not implemented'] },
]

function flattenAst(node, path = 'Module', nodes = []) {
  if (!node || typeof node !== 'object') return nodes
  if (node.type) nodes.push({ type: node.type, line: node.line, path })
  ;(node.children || []).forEach((child, index) => flattenAst(child, `${path} / ${child.type || 'node'} ${index + 1}`, nodes))
  return nodes
}

function layoutAstGraph(root) {
  const nodeWidth = 164
  const nodeHeight = 62
  const horizontalGap = 38
  const verticalGap = 52
  const margin = 30
  const nodes = []
  const edges = []
  let leafCount = 0
  let maxDepth = 0

  function visit(node, depth = 0, parentId = null, inheritedLine = null) {
    if (!node || typeof node !== 'object') return null
    const id = nodes.length
    const line = node.line || inheritedLine
    const graphNode = {
      id,
      type: node.type || 'Node',
      line,
      fields: Object.entries(node.fields || {}).map(([key, value]) => `${key}: ${String(value)}`),
      depth,
      x: 0,
      y: margin + depth * (nodeHeight + verticalGap),
    }
    nodes.push(graphNode)
    maxDepth = Math.max(maxDepth, depth)
    if (parentId !== null) edges.push({ from: parentId, to: id })

    const children = (node.children || []).filter((child) => child && typeof child === 'object')
    if (children.length) {
      const childCenters = children
        .map((child) => visit(child, depth + 1, id, line))
        .filter((center) => center !== null)
      graphNode.x = childCenters.length
        ? childCenters.reduce((sum, center) => sum + center, 0) / childCenters.length
        : margin + nodeWidth / 2 + leafCount++ * (nodeWidth + horizontalGap)
    } else {
      graphNode.x = margin + nodeWidth / 2 + leafCount++ * (nodeWidth + horizontalGap)
    }
    return graphNode.x
  }

  visit(root)
  const width = Math.max(700, margin * 2 + leafCount * nodeWidth + Math.max(0, leafCount - 1) * horizontalGap)
  const height = margin * 2 + (maxDepth + 1) * nodeHeight + maxDepth * verticalGap
  return { nodes, edges, nodeWidth, nodeHeight, width, height }
}

function AstGraph({ ast, selectedLine, onSelectLine }) {
  const svgRef = useRef(null)
  const [exportError, setExportError] = useState('')
  const [exportMessage, setExportMessage] = useState('')
  const graph = layoutAstGraph(ast)

  async function downloadPng() {
    if (!svgRef.current) return
    setExportError('')
    setExportMessage('')
    const svgBlob = new Blob(
      [new XMLSerializer().serializeToString(svgRef.current)],
      { type: 'image/svg+xml;charset=utf-8' },
    )
    const svgUrl = URL.createObjectURL(svgBlob)
    try {
      const image = new Image()
      await new Promise((resolve, reject) => {
        image.onload = resolve
        image.onerror = () => reject(new Error('The graph image could not be prepared.'))
        image.src = svgUrl
      })
      const scale = Math.min(2, 4096 / graph.width, 4096 / graph.height)
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(graph.width * scale))
      canvas.height = Math.max(1, Math.round(graph.height * scale))
      const context = canvas.getContext('2d')
      if (!context) throw new Error('Image export is unavailable in this browser.')
      context.fillStyle = '#08111d'
      context.fillRect(0, 0, canvas.width, canvas.height)
      context.drawImage(image, 0, 0, canvas.width, canvas.height)
      const png = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
      if (!png) throw new Error('The browser could not create the PNG image.')
      const pngUrl = URL.createObjectURL(png)
      const download = document.createElement('a')
      download.href = pngUrl
      download.download = `codelens-ast-graph-line-${selectedLine || 'all'}.png`
      document.body.appendChild(download)
      download.click()
      download.remove()
      setExportMessage('PNG graph download started.')
      window.setTimeout(() => URL.revokeObjectURL(pngUrl), 1000)
    } catch (error) {
      setExportError(error.message || 'Could not export the graph image.')
    } finally {
      URL.revokeObjectURL(svgUrl)
    }
  }

  function selectNode(event, line) {
    if (!line || (event.type === 'keydown' && event.key !== 'Enter' && event.key !== ' ')) return
    if (event.type === 'keydown') event.preventDefault()
    onSelectLine(line)
  }

  return (
    <div className="ast-graph-wrap">
      <div className="ast-graph-toolbar">
        <span>Syntax tree · click a node to select its Python line</span>
        <button className="subtle-button" onClick={downloadPng} disabled={!graph.nodes.length}>Download PNG</button>
      </div>
      {exportError && <p className="graph-export-error" role="alert">{exportError}</p>}
      {exportMessage && <p className="graph-export-status" role="status">{exportMessage}</p>}
      <div className="ast-graph-scroll">
        <svg
          ref={svgRef}
          className="ast-graph"
          xmlns="http://www.w3.org/2000/svg"
          width={graph.width}
          height={graph.height}
          viewBox={`0 0 ${graph.width} ${graph.height}`}
          role="group"
          aria-label="Graphical Python abstract syntax tree"
        >
          <defs>
            <marker id="ast-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#627a98" />
            </marker>
          </defs>
          <rect width={graph.width} height={graph.height} fill="#08111d" />
          {graph.edges.map(({ from, to }) => {
            const parent = graph.nodes[from]
            const child = graph.nodes[to]
            const startY = parent.y + graph.nodeHeight
            const endY = child.y - 3
            const middleY = startY + (endY - startY) / 2
            return <path key={`${from}-${to}`} className="ast-graph-edge" d={`M ${parent.x} ${startY} C ${parent.x} ${middleY}, ${child.x} ${middleY}, ${child.x} ${endY}`} fill="none" stroke="#425773" strokeWidth="1.5" markerEnd="url(#ast-arrow)" />
          })}
          {graph.nodes.map((node) => {
            const selected = selectedLine === node.line
            const left = node.x - graph.nodeWidth / 2
            const label = node.fields[0]?.replace(/\s+/g, ' ') || (node.line ? `Python line ${node.line}` : 'syntax node')
            const shortLabel = label.length > 24 ? `${label.slice(0, 21)}…` : label
            return (
              <g
                key={node.id}
                className={`ast-graph-node ${selected ? 'selected' : ''}`}
                role={node.line ? 'button' : undefined}
                tabIndex={node.line ? 0 : undefined}
                aria-label={`${node.type}${node.line ? `, Python line ${node.line}` : ''}${node.fields.length ? `, ${node.fields.join(', ')}` : ''}`}
                onClick={(event) => selectNode(event, node.line)}
                onKeyDown={(event) => selectNode(event, node.line)}
                style={{ cursor: node.line ? 'pointer' : 'default' }}
              >
                <title>{`${node.type}${node.line ? ` · Python line ${node.line}` : ''}${node.fields.length ? ` · ${node.fields.join(' · ')}` : ''}`}</title>
                <rect x={left} y={node.y} width={graph.nodeWidth} height={graph.nodeHeight} rx="10" fill={selected ? '#123846' : '#111f30'} stroke={selected ? '#60e6ff' : '#334b68'} strokeWidth={selected ? '2' : '1.3'} />
                <text x={node.x} y={node.y + 24} textAnchor="middle" fill={selected ? '#79efff' : '#b9ceff'} fontFamily="ui-monospace, monospace" fontSize="12" fontWeight="700">{node.type}</text>
                <text x={node.x} y={node.y + 43} textAnchor="middle" fill="#8ea4bd" fontFamily="ui-monospace, monospace" fontSize="9">{node.line ? `line ${node.line}` : shortLabel}</text>
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
}

function FeatureMatrix({ target }) {
  const targetName = target === 'cpp' ? 'C++' : target.toUpperCase()
  return (
    <section className="feature-matrix" aria-label="Python feature support by target">
      <div className="feature-heading">
        <div><span className="section-kicker">TARGET CAPABILITIES</span><h2>Supported-feature matrix</h2></div>
        <span>Current target: <strong>{targetName}</strong></span>
      </div>
      <p className="feature-caption">Support describes this translator's documented subset, not all of Python. Partial rows list their limits; unsupported constructs receive a line-specific translation diagnostic.</p>
      <div className="table-wrap feature-table-wrap">
        <table>
          <thead><tr><th>PYTHON CONSTRUCT</th><th>JAVA</th><th>C++</th><th>C</th></tr></thead>
          <tbody>{featureMatrix.map((feature) => (
            <tr key={feature.name} className="feature-row">
              <td>{feature.name}</td>
              {['java', 'cpp', 'c'].map((language) => {
                const [status, detail] = feature[language]
                return <td key={language} className={target === language ? 'feature-current-target' : ''} title={detail || `${feature.name} is supported`}>
                  <span className={`support-badge ${status}`}>{status}</span>{detail && <span className="support-detail">{detail}</span>}
                </td>
              })}
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  )
}

function Icon({ name, size = 18 }) {
  const paths = {
    code: <><path d="m7 5-5 7 5 7" /><path d="m17 5 5 7-5 7" /><path d="m14 3-4 18" /></>,
    play: <path d="m7 4 14 8-14 8z" fill="currentColor" stroke="none" />,
    copy: <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    chevron: <path d="m9 18 6-6-6-6" />,
    spark: <><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /><path d="m19 14 .9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9z" /></>,
  }
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>
}

function TreeNode({ node, depth = 0, selectedLine, onSelectLine }) {
  const children = node.children || []
  const details = Object.entries(node.fields || {})
  const title = `${node.type}${node.line ? ` · line ${node.line}` : ''}`

  if (!children.length && !details.length) {
    return <button className={`tree-leaf ${selectedLine === node.line ? 'selected' : ''}`} style={{ '--depth': depth }} onClick={() => node.line && onSelectLine?.(node.line)} disabled={!node.line} title={title}><span className="tree-dot" />{title}</button>
  }

  return (
    <details className="tree-node" open={depth < 1}>
      <summary className={selectedLine === node.line ? 'selected' : ''} style={{ '--depth': depth }} onClick={() => node.line && onSelectLine?.(node.line)} title={title}>
        <span className="tree-chevron"><Icon name="chevron" size={14} /></span>
        <span className="tree-type">{node.type}</span>
        {node.line && <span className="tree-line">line {node.line}</span>}
      </summary>
      {details.map(([key, value]) => (
        <div className="tree-field" style={{ '--depth': depth + 1 }} key={key}>
          <span>{key}</span><code>{String(value)}</code>
        </div>
      ))}
      {children.map((child, index) => <TreeNode node={child} depth={depth + 1} selectedLine={selectedLine} onSelectLine={onSelectLine} key={`${child.type}-${index}`} />)}
    </details>
  )
}

function StageState({ status }) {
  if (!status) return <span className="stage-state pending">Waiting</span>
  return <span className={`stage-state ${status}`}>{status === 'success' ? 'Complete' : status === 'error' ? 'Needs attention' : 'Skipped'}</span>
}

function ErrorNotice({ children }) {
  if (!children) return null
  return <div className="notice notice-error" role="alert">{children}</div>
}

function DiagnosticList({ diagnostics, onSelect }) {
  if (!diagnostics?.length) return null
  return (
    <div className="diagnostic-list" aria-label="Source diagnostics">
      {diagnostics.map((diagnostic, index) => (
        <button
          className="diagnostic-link"
          key={`${diagnostic.source}-${diagnostic.line}-${index}`}
          onClick={() => onSelect(diagnostic)}
          disabled={!diagnostic.line}
        >
          {diagnostic.line ? `${diagnostic.source === 'java' ? 'Java' : 'Python'} line ${diagnostic.line}: ` : ''}
          {diagnostic.message}
        </button>
      ))}
    </div>
  )
}

function insertIndent(event, setCode) {
  if (event.key !== 'Tab') return

  event.preventDefault()
  const editor = event.currentTarget
  const start = editor.selectionStart
  const end = editor.selectionEnd
  const updatedCode = `${editor.value.slice(0, start)}    ${editor.value.slice(end)}`

  setCode(updatedCode)
  requestAnimationFrame(() => editor.setSelectionRange(start + 4, start + 4))
}

function LinkedSourceExplorer({ code, ast, symbols, output, sourceMap, selectedLine, onSelectLine, onSelectGeneratedLine }) {
  const astNodes = flattenAst(ast)
  const line = selectedLine || (code.trim() ? 1 : null)
  const sourceLine = line ? code.split('\n')[line - 1] : ''
  const lineNodes = astNodes.filter((node) => node.line === line)
  const lineNames = new Set(sourceLine?.match(/[A-Za-z_]\w*/g) || [])
  const lineSymbols = (symbols || []).filter((symbol) => symbol.line === line || lineNames.has(symbol.name))
  const generatedLines = sourceMap?.flatMap((sourceLineNumber, index) => sourceLineNumber === line ? [index + 1] : []) || []
  const outputLines = output.split('\n')

  return (
    <section className="linked-explorer" aria-label="Source, syntax tree, types, and generated code explorer">
      <div className="linked-heading">
        <div><span className="section-kicker">SOURCE-TO-CODE TRACE</span><h3>Explore one Python line</h3></div>
        <label>Line <select aria-label="Select Python source line" value={line || ''} onChange={(event) => onSelectLine(Number(event.target.value))}>
          {code.split('\n').map((_, index) => <option value={index + 1} key={index}>{index + 1}</option>)}
        </select></label>
      </div>
      <div className="linked-source"><span>{line ? `Python · line ${line}` : 'Python source'}</span><code>{sourceLine || '(blank line)'}</code></div>
      <div className="linked-grid">
        <div className="linked-tree">
          <h4>Graphical syntax tree</h4>
          {ast ? <AstGraph ast={ast} selectedLine={line} onSelectLine={onSelectLine} /> : <p className="table-empty">Translate the source to build its syntax tree.</p>}
          {lineNodes.length > 0 && <div className="node-trail">{lineNodes.map((node, index) => <span key={`${node.path}-${index}`}>{node.type}</span>)}</div>}
        </div>
        <div className="linked-inspector">
          <h4>Inferred types</h4>
          {lineSymbols.length ? lineSymbols.map((symbol, index) => (
            <button className="linked-symbol" key={`${symbol.scope}-${symbol.name}-${index}`} onClick={() => onSelectLine(symbol.line)}>
              <code>{symbol.name}</code><span>{symbol.inferred_type}</span><small>{symbol.scope} · line {symbol.line}</small>
            </button>
          )) : <p className="table-empty">No symbol is declared on this line.</p>}
          <h4>Generated {sourceMap ? 'code · mapped lines' : 'code mapping'}</h4>
          {generatedLines.length ? <div className="generated-links">{generatedLines.map((generatedLine) => (
            <button key={generatedLine} onClick={() => onSelectGeneratedLine(generatedLine)}>
              <span>line {generatedLine}</span><code>{outputLines[generatedLine - 1]?.trim() || '(blank line)'}</code>
            </button>
          ))}</div> : <p className="table-empty">{sourceMap ? 'No generated line maps to this source line.' : 'Mapping unavailable for this translation.'}</p>}
          {sourceMap && <p className="mapping-note">Mappings identify related generated lines; compiler scaffolding may share a source line.</p>}
        </div>
      </div>
    </section>
  )
}

function App() {
  const [code, setCode] = useState(starterCode)
  const [editedOutput, setEditedOutput] = useState('')
  const [outputMapValid, setOutputMapValid] = useState(true)
  const [selectedPythonLine, setSelectedPythonLine] = useState(null)
  const [selectedJavaLine, setSelectedJavaLine] = useState(null)
  const [stdin, setStdin] = useState('')
  const [target, setTarget] = useState('java')
  const [samples, setSamples] = useState([])
  const [sampleName, setSampleName] = useState('')
  const [sampleError, setSampleError] = useState('')
  const [result, setResult] = useState(null)
  const [activeStage, setActiveStage] = useState('lex')
  const [isTranslating, setIsTranslating] = useState(false)
  const [requestError, setRequestError] = useState('')
  const [showRawAst, setShowRawAst] = useState(false)
  const [copied, setCopied] = useState(false)
  const [execution, setExecution] = useState(null)
  const [isExecuting, setIsExecuting] = useState(false)
  const [executionError, setExecutionError] = useState('')
  const pythonEditorRef = useRef(null)
  const javaEditorRef = useRef(null)
  const targetName = target === 'cpp' ? 'C++' : target === 'c' ? 'C' : 'Java'

  useEffect(() => {
    fetch('/api/samples')
      .then(async (response) => {
        if (!response.ok) throw new Error(`Could not load examples (${response.status}).`)
        return response.json()
      })
      .then((items) => setSamples(items))
      .catch((error) => setSampleError(error.message))
  }, [])

  async function translateCode() {
    setIsTranslating(true)
    setRequestError('')
    setResult(null)
    setCopied(false)
    try {
      const response = await fetch('/api/pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, target }),
      })
      const data = await response.json()
      if (!response.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}).`
        throw new Error(detail)
      }
      setResult(data)
      const translatedSource = data.translate?.result?.code ?? data.translate?.result?.java_code
      setEditedOutput(translatedSource || '')
      setOutputMapValid(true)
      setExecution(null)
      setExecutionError('')
      setActiveStage('lex')
      setShowRawAst(false)
    } catch (error) {
      setRequestError(error.message)
    } finally {
      setIsTranslating(false)
    }
  }

  function selectSample(event) {
    const selected = samples.find((sample) => sample.name === event.target.value)
    setSampleName(event.target.value)
    if (selected) {
      setCode(selected.code)
      setResult(null)
      setExecution(null)
      setEditedOutput('')
      setOutputMapValid(true)
    }
  }

  async function compileAndRun() {
    setIsExecuting(true)
    setExecution(null)
    setExecutionError('')
    try {
      const response = await fetch('/api/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          python_code: code,
          java_code: editedOutput,
          stdin,
          source_map: outputMapValid ? result?.translate?.result?.source_map : null,
        }),
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : `Run failed (${response.status}).`)
      }
      setExecution(data)
    } catch (error) {
      setExecutionError(error.message)
    } finally {
      setIsExecuting(false)
    }
  }

  function selectLine(editor, source) {
    const sourceText = source === 'java' ? editedOutput : code
    const line = sourceText.slice(0, editor.selectionStart).split('\n').length
    if (source === 'java') setSelectedJavaLine(line)
    else setSelectedPythonLine(line)
    const sourceMap = outputMapValid ? result?.translate?.result?.source_map : null
    if (!sourceMap) return
    if (source === 'java') {
      setSelectedPythonLine(sourceMap[line - 1] ?? null)
    } else {
      const javaLine = sourceMap.indexOf(line)
      setSelectedJavaLine(javaLine < 0 ? null : javaLine + 1)
    }
  }

  function selectSourceLine(line) {
    setSelectedPythonLine(line)
    const sourceMap = outputMapValid ? result?.translate?.result?.source_map : null
    const generatedIndex = sourceMap?.findIndex((sourceLine) => sourceLine === line) ?? -1
    setSelectedJavaLine(generatedIndex < 0 ? null : generatedIndex + 1)
  }

  function selectGeneratedLine(line) {
    setSelectedJavaLine(line)
    const mappedSourceLine = outputMapValid ? result?.translate?.result?.source_map?.[line - 1] : null
    setSelectedPythonLine(mappedSourceLine ?? null)
    const editor = javaEditorRef.current
    if (!editor) return
    const lines = editedOutput.split('\n')
    const start = lines.slice(0, line - 1).reduce((offset, value) => offset + value.length + 1, 0)
    const end = start + (lines[line - 1] || '').length
    requestAnimationFrame(() => {
      editor.focus()
      editor.setSelectionRange(start, end)
    })
  }

  function selectDiagnostic(diagnostic, stageId) {
    setActiveStage(stageId)
    const editor = diagnostic.source === 'java' ? javaEditorRef.current : pythonEditorRef.current
    const source = diagnostic.source === 'java' ? editedOutput : code
    if (!editor || !diagnostic.line) return
    if (diagnostic.source === 'java') {
      setSelectedJavaLine(diagnostic.line)
      setSelectedPythonLine(diagnostic.python_line ?? null)
    } else {
      setSelectedPythonLine(diagnostic.line)
      const sourceMap = outputMapValid ? result?.translate?.result?.source_map : null
      const javaLine = sourceMap?.indexOf(diagnostic.line) ?? -1
      setSelectedJavaLine(javaLine < 0 ? null : javaLine + 1)
    }
    const lines = source.split('\n')
    const line = Math.min(Math.max(diagnostic.line - 1, 0), lines.length - 1)
    const start = lines.slice(0, line).reduce((offset, value) => offset + value.length + 1, 0)
    const end = start + lines[line].length
    requestAnimationFrame(() => {
      editor.focus()
      editor.setSelectionRange(start, end)
    })
  }

  async function copyTranslation() {
    const translatedCode = translation?.code ?? translation?.java_code
    if (!translatedCode) return
    try {
      await navigator.clipboard.writeText(translatedCode)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setRequestError('Could not access the clipboard. Select and copy the generated code instead.')
    }
  }

  const stage = result?.[activeStage]
  const ast = result?.parse?.result?.ast
  const semantic = result?.semantic?.result
  const translation = result?.translate?.result
  const validation = result?.validate?.result

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#" aria-label="CodeLens Translator home">
          <span className="brand-mark"><Icon name="code" size={20} /></span>
          <span>CodeLens<span className="brand-light"> Translator</span></span>
        </a>
        <div className="topbar-right"><span className="live-dot" /> Compiler playground <span className="version-pill">v1.0</span></div>
      </header>

      <main>
        <section className="intro">
          <div className="eyebrow"><Icon name="spark" size={16} /> A compiler, made visible</div>
          <h1>See how your code <span>comes to life.</span></h1>
          <p>Follow Python through every compiler stage, from its first token to ready-to-check {targetName}.</p>
        </section>

        <section className="workspace" aria-label="Python and generated source editors">
          <div className="editors-grid">
            <section className="editor-column" aria-label="Python source editor">
              <div className="editor-heading">
                <div className="section-label"><span className="language-dot python-dot" /> Python source</div>
                <div className="editor-controls">
                  <label className="sample-picker">
                    <span className="sr-only">Load a sample program</span>
                    <select value={sampleName} onChange={selectSample} disabled={!samples.length}>
                      <option value="">{samples.length ? 'Load a sample…' : 'Loading samples…'}</option>
                      {samples.map((sample) => <option value={sample.name} key={sample.name}>{sample.name}</option>)}
                    </select>
                  </label>
                </div>
              </div>
              <ErrorNotice>{sampleError}</ErrorNotice>
              <div className="editor-frame">
                <div className="line-numbers" aria-hidden="true">{code.split('\n').map((_, index) => <span className={selectedPythonLine === index + 1 ? 'highlighted' : ''} key={index}>{String(index + 1).padStart(2, '0')}</span>)}</div>
                <textarea
                  ref={pythonEditorRef}
                  aria-label="Python source code"
                  spellCheck="false"
                  value={code}
                  onKeyDown={(event) => insertIndent(event, setCode)}
                  onClick={(event) => selectLine(event.currentTarget, 'python')}
                  onKeyUp={(event) => selectLine(event.currentTarget, 'python')}
                  onChange={(event) => {
                    setCode(event.target.value)
                    setSampleName('')
                    setResult(null)
                    setExecution(null)
                    setEditedOutput('')
                    setOutputMapValid(false)
                  }}
                />
              </div>
              <div className="editor-footer">
                <label className="target-picker">
                  <span className="sr-only">Output language</span>
                  <select value={target} onChange={(event) => { setTarget(event.target.value); setResult(null); setExecution(null); setEditedOutput(''); setRequestError('') }}>
                    <option value="java">Java</option>
                    <option value="cpp">C++</option>
                    <option value="c">C</option>
                  </select>
                </label>
                <button className="translate-button" onClick={translateCode} disabled={isTranslating || !code.trim()}>
                  {isTranslating ? <span className="spinner" /> : <Icon name="play" size={15} />}
                  {isTranslating ? 'Analyzing…' : 'Translate'}
                </button>
              </div>
              <ErrorNotice>{requestError}</ErrorNotice>
            </section>

            <section className="editor-column target-column" aria-label="Editable generated source editor">
              <div className="editor-heading">
                <div className="section-label"><span className={`language-dot ${target === 'java' ? 'java-dot' : 'native-dot'}`} /> {targetName} output <span className="edit-label">editable</span></div>
                {result?.translate?.result && <button className="copy-button" onClick={copyTranslation}><Icon name={copied ? 'check' : 'copy'} size={14} />{copied ? 'Copied' : 'Copy'}</button>}
              </div>
              <div className="editor-frame">
                <div className="line-numbers" aria-hidden="true">{(editedOutput || ' ').split('\n').map((_, index) => <span className={selectedJavaLine === index + 1 ? 'highlighted' : ''} key={index}>{String(index + 1).padStart(2, '0')}</span>)}</div>
                <textarea
                  ref={javaEditorRef}
                  aria-label={`Editable ${targetName} output`}
                  spellCheck="false"
                  value={editedOutput}
                  placeholder="Translate Python to generate editable output…"
                  onClick={(event) => selectLine(event.currentTarget, 'java')}
                  onKeyUp={(event) => selectLine(event.currentTarget, 'java')}
                  onChange={(event) => { setEditedOutput(event.target.value); setOutputMapValid(false); setExecution(null); setExecutionError('') }}
                />
              </div>
              {target === 'java' && (
                <div className="run-controls">
                  <label className="stdin-field">
                    <span>Program input</span>
                    <textarea aria-label="Program input" value={stdin} onChange={(event) => setStdin(event.target.value)} placeholder="Optional input for input() calls" rows="2" />
                  </label>
                  <button className="run-button" onClick={compileAndRun} disabled={isExecuting || !result || !editedOutput.trim()}>
                    {isExecuting ? <span className="spinner" /> : <Icon name="play" size={14} />}
                    {isExecuting ? 'Running…' : 'Compile & compare'}
                  </button>
                </div>
              )}
              {executionError && <ErrorNotice>{executionError}</ErrorNotice>}
              {execution && (
                <div className="execution-results" aria-live="polite">
                  <div className={`execution-summary ${execution.comparison?.status}`}>
                    {execution.comparison?.status === 'match' ? 'Python and Java output match' : execution.comparison?.status === 'different' ? 'Python and Java output differ' : 'Execution completed with issues'}
                  </div>
                  <div className="execution-columns">
                    <div><strong>Compile</strong><pre>{execution.compile.output || execution.compile.error || 'Compilation succeeded.'}</pre></div>
                    {execution.python && <div><strong>Python output · {execution.python.status}</strong><pre>{execution.python.output || execution.python.error || '(no output)'}</pre></div>}
                    {execution.java && <div><strong>Java output · {execution.java.status}</strong><pre>{execution.java.output || execution.java.error || '(no output)'}</pre></div>}
                  </div>
                  <DiagnosticList
                    diagnostics={execution.compile.diagnostics}
                    onSelect={(diagnostic) => selectDiagnostic(diagnostic, 'validate')}
                  />
                </div>
              )}
              <p className="local-run-warning">Local educational execution only. Do not run untrusted code or expose this app publicly.</p>
            </section>
          </div>
        </section>

        <FeatureMatrix target={target} />

        <section className="pipeline-section" aria-label="Compiler pipeline results">
          <div className="pipeline-heading">
            <div><span className="section-kicker">THE PIPELINE</span><h2>From Python to {targetName}</h2></div>
            {result && <span className="run-complete"><Icon name="check" size={14} /> Run complete</span>}
          </div>
          <div className="sr-only" aria-live="polite">{result ? `Translation ready for ${targetName}` : ''}</div>

          <nav className="stage-tabs" aria-label="Compiler stages">
            {stages.map((item, index) => {
              const status = result?.[item.id]?.status
              return (
                <button className={`stage-tab ${activeStage === item.id ? 'active' : ''}`} key={item.id} onClick={() => setActiveStage(item.id)} aria-current={activeStage === item.id ? 'step' : undefined}>
                  <span className={`stage-number ${status || ''}`}>{status === 'success' ? <Icon name="check" size={13} /> : item.number}</span>
                  <span className="stage-copy"><span>{item.name}</span><StageState status={status} /></span>
                  {index < stages.length - 1 && <span className="tab-connector" />}
                </button>
              )
            })}
          </nav>

          <div className="stage-panel">
            <div className="panel-heading">
              <div><span className="panel-number">{stages.find((item) => item.id === activeStage)?.number}</span><h3>{stages.find((item) => item.id === activeStage)?.name}</h3></div>
              <StageState status={stage?.status} />
            </div>
            {!result && <div className="empty-stage"><span className="empty-icon"><Icon name="spark" size={22} /></span><div><strong>Your compiler stages will appear here</strong><p>Write or choose a Python example, then translate it to inspect each step.</p></div></div>}
            {stage?.error && <ErrorNotice>{stage.error}</ErrorNotice>}
            <DiagnosticList diagnostics={stage?.diagnostics} onSelect={(diagnostic) => selectDiagnostic(diagnostic, activeStage)} />

            {activeStage === 'lex' && stage?.result && (
              <div className="table-wrap">
                <table><thead><tr><th>TYPE</th><th>VALUE</th><th>LINE</th><th>COLUMN</th></tr></thead>
                  <tbody>{stage.result.tokens.map((token, index) => <tr key={`${token.line}-${token.column}-${index}`}><td><span className={`token-type token-${token.type.toLowerCase()}`}>{token.type}</span></td><td><code className="token-value">{token.value === '\n' ? '\\n' : token.value || '—'}</code></td><td>{token.line}</td><td>{token.column}</td></tr>)}</tbody>
                </table>
              </div>
            )}

            {activeStage === 'parse' && ast && (
              <div className="ast-view">
                <div className="ast-toolbar"><span>Python abstract syntax tree</span><button className="subtle-button" onClick={() => setShowRawAst(!showRawAst)}>{showRawAst ? 'Show tree' : 'View raw JSON'}</button></div>
                {showRawAst ? <pre className="code-block json-block">{JSON.stringify(ast, null, 2)}</pre> : <div className="tree-view"><TreeNode node={ast} selectedLine={selectedPythonLine} onSelectLine={selectSourceLine} /></div>}
              </div>
            )}

            {activeStage === 'semantic' && semantic && (
              <div className="semantic-view">
                {ast && <LinkedSourceExplorer
                  code={code}
                  ast={ast}
                  symbols={semantic.symbols}
                  output={editedOutput}
                  sourceMap={outputMapValid ? translation?.source_map : null}
                  selectedLine={selectedPythonLine}
                  onSelectLine={selectSourceLine}
                  onSelectGeneratedLine={selectGeneratedLine}
                />}
                <div className="table-wrap"><table><thead><tr><th>VARIABLE</th><th>INFERRED TYPE</th><th>SCOPE</th><th>LINE</th></tr></thead>
                  <tbody>{semantic.symbols.map((symbol, index) => <tr className={selectedPythonLine === symbol.line ? 'selected-symbol-row' : ''} key={`${symbol.scope}-${symbol.name}-${index}`}><td><code className="symbol-name">{symbol.name}</code></td><td><span className="type-pill">{symbol.inferred_type}</span></td><td>{symbol.scope}</td><td><button className="symbol-line-link" onClick={() => selectSourceLine(symbol.line)} aria-label={`Select Python line ${symbol.line} for ${symbol.name}`}>{symbol.line}</button></td></tr>)}</tbody>
                </table>{semantic.symbols.length === 0 && <p className="table-empty">No variables or functions were declared.</p>}</div>
                {semantic.warnings?.map((warning, index) => <div className="notice notice-warning" key={`warning-${index}`}><strong>Warning</strong> {warning}</div>)}
              </div>
            )}

            {activeStage === 'translate' && translation && (
              <div className="java-view">
                <div className="code-toolbar"><span><span className="language-dot java-dot" /> {translation.target === 'cpp' ? 'C++' : translation.target === 'c' ? 'C' : 'Java'} output <span className="method-pill">{translation.method === 'huggingface' ? 'Hugging Face model' : translation.method === 'ml' ? 'CodeT5 model' : 'Rule-based'}</span></span>
                  <button className="copy-button" onClick={copyTranslation}><Icon name={copied ? 'check' : 'copy'} size={15} />{copied ? 'Copied' : 'Copy code'}</button>
                </div>
                {translation.fallback_reason && <div className="notice notice-info">{translation.fallback_reason}</div>}
                {translation.ast && (
                  <details className="ast-view">
                    <summary>AST returned by {translation.model || 'the model'}</summary>
                    <pre className="code-block json-block">{JSON.stringify(translation.ast, null, 2)}</pre>
                  </details>
                )}
                <pre className="code-block java-code"><code>{translation.code ?? translation.java_code}</code></pre>
              </div>
            )}

            {activeStage === 'validate' && validation && (
              <div className="validation-view">
                <div className={`validation-result ${validation.is_valid ? 'valid' : 'invalid'}`}>
                  <span className="validation-icon">{validation.is_valid ? <Icon name="check" size={21} /> : '!'}</span>
                  <div><strong>{validation.is_valid ? `${targetName} syntax looks good` : `${targetName} syntax needs attention`}</strong><p>{validation.is_valid ? 'The generated output parsed successfully.' : `${validation.errors.length} syntax issue${validation.errors.length === 1 ? '' : 's'} found.`}</p></div>
                </div>
                {validation.confidence !== null ? <div className="confidence-card">
                  <div className="confidence-heading"><span>Translation confidence</span><strong>{validation.confidence}%</strong></div>
                  <div className="confidence-track"><span style={{ width: `${validation.confidence}%` }} /></div>
                  <p>{translation?.method === 'ml' ? 'Mean probability across generated model tokens.' : 'Based on supported-construct coverage for the rule-based translator.'}</p>
                </div> : <div className="confidence-card">
                  <div className="confidence-heading"><span>Translation confidence</span><strong>N/A</strong></div>
                  <p>The Hugging Face provider does not supply a comparable confidence score. Generated syntax is checked separately.</p>
                </div>}
              </div>
            )}
          </div>
        </section>

        <footer className="page-footer"><span>Built to make compiler design easier to understand.</span><span>LEX <b>→</b> PARSE <b>→</b> ANALYZE <b>→</b> TRANSLATE</span></footer>
      </main>
    </div>
  )
}

export default App
