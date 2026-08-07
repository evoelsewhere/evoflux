import { describe, expect, it } from 'vitest'

import {
  getSkillBundleChanges,
  skillBundleFilesFromApi,
} from '@/components/settings/skillBundle'
import type { SkillBundleFile } from '@/api/types'

const executableScript: SkillBundleFile = {
  path: 'scripts/check.sh',
  size: 18,
  media_type: 'text/x-shellscript',
  content: '#!/bin/sh\necho ok\n',
  encoding: 'utf-8',
  editable: true,
}

describe('skill bundle changes', () => {
  it('does not resubmit an unchanged editable resource', () => {
    const files = skillBundleFilesFromApi([executableScript])

    expect(getSkillBundleChanges(files, [])).toEqual({
      files: [],
      deletedFiles: [],
    })
  })

  it('submits only resources whose content changed', () => {
    const [script] = skillBundleFilesFromApi([executableScript])
    const changed = { ...script, content: '#!/bin/sh\necho changed\n' }

    expect(getSkillBundleChanges([changed], [])).toEqual({
      files: [{
        path: 'scripts/check.sh',
        content: '#!/bin/sh\necho changed\n',
        encoding: 'utf-8',
      }],
      deletedFiles: [],
    })
  })

  it('writes a renamed resource and deletes its original path', () => {
    const [script] = skillBundleFilesFromApi([executableScript])
    const renamed = { ...script, path: 'scripts/verify.sh' }

    expect(getSkillBundleChanges([renamed], [])).toEqual({
      files: [{
        path: 'scripts/verify.sh',
        content: executableScript.content,
        encoding: 'utf-8',
      }],
      deletedFiles: ['scripts/check.sh'],
    })
  })

  it('writes every new resource', () => {
    expect(getSkillBundleChanges([{
      path: 'references/notes.md',
      content: '# Notes',
      encoding: 'utf-8',
      size: 7,
      mediaType: 'text/markdown',
      editable: true,
    }], [])).toEqual({
      files: [{
        path: 'references/notes.md',
        content: '# Notes',
        encoding: 'utf-8',
      }],
      deletedFiles: [],
    })
  })
})
