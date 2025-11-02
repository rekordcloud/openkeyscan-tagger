#!/usr/bin/env node
/**
 * Debug script to inspect metadata from an audio file
 */

import { parseFile } from 'music-metadata';
import { resolve } from 'path';

const filePath = process.argv[2] || './test-files/test.mp3';
const absolutePath = resolve(filePath);

console.log(`\nInspecting: ${absolutePath}\n`);

try {
  const metadata = await parseFile(absolutePath);

  console.log('=== Common Tags ===');
  console.log('key:', metadata.common.key);
  console.log('initialKey:', metadata.common.initialKey);

  console.log('\n=== Native Tags ===');
  if (metadata.native) {
    for (const [format, tags] of Object.entries(metadata.native)) {
      console.log(`\n${format}:`);
      tags.forEach(tag => {
        console.log(`  ${tag.id}:`, tag.value);
      });
    }
  }

} catch (err) {
  console.error('Error:', err.message);
}
