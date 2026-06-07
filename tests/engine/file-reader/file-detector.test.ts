import { describe, it, expect } from 'vitest'
import { detectFileType, getExtension, getFileName, isBinaryFile, shouldSkipFile, getLanguage } from '../../../src/engine/file-reader/file-detector'

describe('FileDetector', () => {
  it('should detect code files', () => {
    const info = detectFileType('app.ts')
    expect(info.category).toBe('code')
    expect(info.language).toBe('ts')
    expect(info.isBinary).toBe(false)
    expect(info.parser).toBe('plain')
  })

  it('should detect markdown files', () => {
    const info = detectFileType('README.md')
    expect(info.category).toBe('markdown')
    expect(info.parser).toBe('markdown')
  })

  it('should detect config files', () => {
    const info = detectFileType('config.json')
    expect(info.category).toBe('config')
  })

  it('should detect office files as binary', () => {
    const info = detectFileType('report.docx')
    expect(info.category).toBe('office')
    expect(info.isBinary).toBe(true)
    expect(info.parser).toBe('markitdown')
  })

  it('should detect PDF files', () => {
    const info = detectFileType('paper.pdf')
    expect(info.category).toBe('pdf')
    expect(info.isBinary).toBe(true)
    expect(info.parser).toBe('markitdown')
  })

  it('should detect image files as binary', () => {
    const info = detectFileType('photo.png')
    expect(info.category).toBe('image')
    expect(info.isBinary).toBe(true)
  })

  it('should detect binary files to skip', () => {
    expect(shouldSkipFile('lib.dll')).toBe(true)
    expect(shouldSkipFile('app.exe')).toBe(true)
    expect(shouldSkipFile('font.woff')).toBe(true)
  })

  it('should not skip text files', () => {
    expect(shouldSkipFile('app.ts')).toBe(false)
    expect(shouldSkipFile('README.md')).toBe(false)
  })

  it('should get extension', () => {
    expect(getExtension('file.ts')).toBe('ts')
    expect(getExtension('path/to/file.json')).toBe('json')
    expect(getExtension('noext')).toBe('')
  })

  it('should get filename', () => {
    expect(getFileName('/path/to/file.ts')).toBe('file.ts')
    expect(getFileName('C:\\Users\\file.ts')).toBe('file.ts')
    expect(getFileName('file.ts')).toBe('file.ts')
  })

  it('should get language', () => {
    expect(getLanguage('app.py')).toBe('py')
    expect(getLanguage('style.css')).toBe('css')
    expect(getLanguage('README.md')).toBe('markdown')
  })
})
