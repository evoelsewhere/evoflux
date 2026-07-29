import fileIcon from 'material-icon-theme/icons/file.svg'
import folderIcon from 'material-icon-theme/icons/folder.svg'
import folderOpenIcon from 'material-icon-theme/icons/folder-open.svg'
import audioIcon from 'material-icon-theme/icons/audio.svg'
import cIcon from 'material-icon-theme/icons/c.svg'
import consoleIcon from 'material-icon-theme/icons/console.svg'
import cppIcon from 'material-icon-theme/icons/cpp.svg'
import cssIcon from 'material-icon-theme/icons/css.svg'
import databaseIcon from 'material-icon-theme/icons/database.svg'
import dockerIcon from 'material-icon-theme/icons/docker.svg'
import drawioIcon from 'material-icon-theme/icons/drawio.svg'
import gitIcon from 'material-icon-theme/icons/git.svg'
import goIcon from 'material-icon-theme/icons/go.svg'
import htmlIcon from 'material-icon-theme/icons/html.svg'
import imageIcon from 'material-icon-theme/icons/image.svg'
import javaIcon from 'material-icon-theme/icons/java.svg'
import javascriptIcon from 'material-icon-theme/icons/javascript.svg'
import jsonIcon from 'material-icon-theme/icons/json.svg'
import kotlinIcon from 'material-icon-theme/icons/kotlin.svg'
import lessIcon from 'material-icon-theme/icons/less.svg'
import licenseIcon from 'material-icon-theme/icons/license.svg'
import lockIcon from 'material-icon-theme/icons/lock.svg'
import makefileIcon from 'material-icon-theme/icons/makefile.svg'
import markdownIcon from 'material-icon-theme/icons/markdown.svg'
import nodejsIcon from 'material-icon-theme/icons/nodejs.svg'
import npmIcon from 'material-icon-theme/icons/npm.svg'
import pdfIcon from 'material-icon-theme/icons/pdf.svg'
import phpIcon from 'material-icon-theme/icons/php.svg'
import powerpointIcon from 'material-icon-theme/icons/powerpoint.svg'
import pythonIcon from 'material-icon-theme/icons/python.svg'
import reactIcon from 'material-icon-theme/icons/react.svg'
import reactTypescriptIcon from 'material-icon-theme/icons/react_ts.svg'
import rubyIcon from 'material-icon-theme/icons/ruby.svg'
import rustIcon from 'material-icon-theme/icons/rust.svg'
import sassIcon from 'material-icon-theme/icons/sass.svg'
import settingsIcon from 'material-icon-theme/icons/settings.svg'
import swiftIcon from 'material-icon-theme/icons/swift.svg'
import tableIcon from 'material-icon-theme/icons/table.svg'
import tomlIcon from 'material-icon-theme/icons/toml.svg'
import typescriptIcon from 'material-icon-theme/icons/typescript.svg'
import videoIcon from 'material-icon-theme/icons/video.svg'
import wordIcon from 'material-icon-theme/icons/word.svg'
import xmlIcon from 'material-icon-theme/icons/xml.svg'
import yamlIcon from 'material-icon-theme/icons/yaml.svg'
import zipIcon from 'material-icon-theme/icons/zip.svg'

const EXTENSION_ICONS: Record<string, string> = {
  js: javascriptIcon,
  mjs: javascriptIcon,
  cjs: javascriptIcon,
  jsx: reactIcon,
  ts: typescriptIcon,
  mts: typescriptIcon,
  cts: typescriptIcon,
  tsx: reactTypescriptIcon,
  py: pythonIcon,
  pyw: pythonIcon,
  rs: rustIcon,
  go: goIcon,
  java: javaIcon,
  c: cIcon,
  h: cIcon,
  cpp: cppIcon,
  cc: cppIcon,
  cxx: cppIcon,
  hpp: cppIcon,
  php: phpIcon,
  rb: rubyIcon,
  swift: swiftIcon,
  kt: kotlinIcon,
  kts: kotlinIcon,
  html: htmlIcon,
  htm: htmlIcon,
  css: cssIcon,
  scss: sassIcon,
  sass: sassIcon,
  less: lessIcon,
  json: jsonIcon,
  jsonl: jsonIcon,
  ndjson: jsonIcon,
  yaml: yamlIcon,
  yml: yamlIcon,
  toml: tomlIcon,
  xml: xmlIcon,
  svg: imageIcon,
  md: markdownIcon,
  markdown: markdownIcon,
  rst: markdownIcon,
  sql: databaseIcon,
  sqlite: databaseIcon,
  db: databaseIcon,
  sh: consoleIcon,
  bash: consoleIcon,
  zsh: consoleIcon,
  fish: consoleIcon,
  ps1: consoleIcon,
  png: imageIcon,
  jpg: imageIcon,
  jpeg: imageIcon,
  gif: imageIcon,
  webp: imageIcon,
  bmp: imageIcon,
  ico: imageIcon,
  pdf: pdfIcon,
  doc: wordIcon,
  docx: wordIcon,
  xls: tableIcon,
  xlsx: tableIcon,
  csv: tableIcon,
  tsv: tableIcon,
  ppt: powerpointIcon,
  pptx: powerpointIcon,
  zip: zipIcon,
  tar: zipIcon,
  gz: zipIcon,
  tgz: zipIcon,
  rar: zipIcon,
  '7z': zipIcon,
  mp3: audioIcon,
  wav: audioIcon,
  flac: audioIcon,
  ogg: audioIcon,
  mp4: videoIcon,
  mov: videoIcon,
  webm: videoIcon,
  mkv: videoIcon,
  drawio: drawioIcon,
  dio: drawioIcon,
}

function basename(path: string): string {
  return path.split(/[\\/]/).pop()?.toLowerCase() ?? path.toLowerCase()
}

function extensionOf(name: string): string {
  const index = name.lastIndexOf('.')
  return index > 0 ? name.slice(index + 1).toLowerCase() : ''
}

function iconForFile(name: string, mime: string): string {
  const lowerName = basename(name)
  if (/^readme(?:\.|$)/.test(lowerName)) return markdownIcon
  if (/^license(?:\.|$)/.test(lowerName)) return licenseIcon
  if (/^(dockerfile|compose\.ya?ml)$/.test(lowerName)) return dockerIcon
  if (/^(makefile|gnumakefile|cmakelists\.txt)$/.test(lowerName)) return makefileIcon
  if (/^package(?:-lock)?\.json$/.test(lowerName)) return lowerName === 'package.json' ? nodejsIcon : npmIcon
  if (/^(yarn|pnpm|bun|cargo|uv)\.lock$/.test(lowerName)) return lockIcon
  if (/^(cargo\.toml|rust-toolchain(?:\.toml)?)$/.test(lowerName)) return rustIcon
  if (/^(pyproject\.toml|requirements.*\.txt|pipfile)$/.test(lowerName)) return pythonIcon
  if (/^(\.gitignore|\.gitattributes|\.gitmodules|\.mailmap)$/.test(lowerName)) return gitIcon
  if (/^(tsconfig|jsconfig).*\.json$/.test(lowerName)) return typescriptIcon
  if (/^(\.env|\.editorconfig|\.npmrc|\.nvmrc|.*config\.(js|ts|json|ya?ml))$/.test(lowerName)) return settingsIcon

  const extensionIcon = EXTENSION_ICONS[extensionOf(lowerName)]
  if (extensionIcon) return extensionIcon
  if (mime.startsWith('image/')) return imageIcon
  if (mime.startsWith('audio/')) return audioIcon
  if (mime.startsWith('video/')) return videoIcon
  if (mime.includes('json')) return jsonIcon
  if (mime.startsWith('text/')) return fileIcon
  return fileIcon
}

function IconImage({ src, size }: { src: string; size: number }) {
  return (
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      draggable={false}
      aria-hidden="true"
      className="pointer-events-none block shrink-0 select-none"
    />
  )
}

export function FileTypeIcon({
  name,
  mime = '',
  size = 16,
}: {
  name: string
  mime?: string
  size?: number
}) {
  return <IconImage src={iconForFile(name, mime)} size={size} />
}

export function FolderTypeIcon({
  open = false,
  size = 16,
}: {
  open?: boolean
  size?: number
}) {
  return <IconImage src={open ? folderOpenIcon : folderIcon} size={size} />
}
