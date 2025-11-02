#!/usr/bin/env node
/**
 * Test suite for key tagging server
 *
 * Tests writing keys to various audio formats and verifies with music-metadata
 */

import { spawn } from 'child_process';
import { createInterface } from 'readline';
import { parseFile } from 'music-metadata';
import { randomUUID } from 'crypto';
import { existsSync } from 'fs';
import { resolve } from 'path';

// Key values to rotate through for testing
const TEST_KEYS = [
  '1A', '2A', '3A', '4A', '5A', '6A', '7A', '8A', '9A', '10A', '11A', '12A',
  '1B', '2B', '3B', '4B', '5B', '6B', '7B', '8B', '9B', '10B', '11B', '12B',
  'C major', 'D minor', 'E minor', 'F major', 'G major', 'A minor',
  '1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '10m', '11m', '12m'
];

// File formats to test
const FILE_FORMATS = [
  { ext: 'mp3', name: 'MP3' },
  { ext: 'mp4', name: 'MP4' },
  { ext: 'm4a', name: 'M4A' },
  { ext: 'aac', name: 'AAC' },
  { ext: 'aiff', name: 'AIFF' },
  { ext: 'aif', name: 'AIF' },
  { ext: 'alac', name: 'ALAC' },
  { ext: 'wav', name: 'WAV' },
  { ext: 'ogg', name: 'OGG' },
  { ext: 'flac', name: 'FLAC' }
];

class KeyTaggingService {
  constructor(executablePath) {
    this.serverProcess = null;
    this.pendingRequests = new Map();
    this.executablePath = executablePath;
    this.isReady = false;
    this._handlers = {};
  }

  start() {
    return new Promise((resolve, reject) => {
      console.log(`Starting server: ${this.executablePath}`);

      // Spawn the server process
      // If it's a .py file, run it through Python
      let command, args;
      if (this.executablePath.endsWith('.py')) {
        command = 'python3';
        args = [this.executablePath, '--workers', '4'];
      } else {
        command = this.executablePath;
        args = ['--workers', '4'];
      }

      this.serverProcess = spawn(command, args);

      // Set up line reader for stdout (responses)
      const rl = createInterface({
        input: this.serverProcess.stdout,
        crlfDelay: Infinity
      });

      // Handle responses
      rl.on('line', (line) => {
        try {
          const response = JSON.parse(line);
          this.handleResponse(response);
        } catch (err) {
          console.error('Failed to parse server response:', err);
        }
      });

      // Monitor stderr for debugging
      this.serverProcess.stderr.on('data', (data) => {
        console.log('[Server]', data.toString().trim());
      });

      // Handle process exit
      this.serverProcess.on('exit', (code) => {
        console.error(`Server exited with code ${code}`);
        this.isReady = false;
      });

      // Wait for ready signal
      const readyTimeout = setTimeout(() => {
        reject(new Error('Server failed to start within 10 seconds'));
      }, 10000);

      this.once('ready', () => {
        clearTimeout(readyTimeout);
        console.log('Server is ready!');
        resolve();
      });
    });
  }

  handleResponse(response) {
    // Handle system messages
    if (response.type === 'ready') {
      this.isReady = true;
      this.emit('ready');
      return;
    }

    if (response.type === 'heartbeat') {
      this.emit('heartbeat');
      return;
    }

    // Handle request responses
    if (response.id && this.pendingRequests.has(response.id)) {
      const { resolve, reject, timeout } = this.pendingRequests.get(response.id);
      clearTimeout(timeout);
      this.pendingRequests.delete(response.id);

      if (response.status === 'success') {
        resolve(response);
      } else {
        reject(new Error(response.error || 'Unknown error'));
      }
    }
  }

  tagFile(filePath, keyValue, timeoutMs = 10000) {
    return new Promise((promiseResolve, promiseReject) => {
      if (!this.isReady) {
        return promiseReject(new Error('Server not ready'));
      }

      // Generate unique request ID
      const requestId = randomUUID();

      // Convert to absolute path
      const absolutePath = resolve(filePath);

      // Set up timeout
      const timeout = setTimeout(() => {
        this.pendingRequests.delete(requestId);
        promiseReject(new Error(`Tagging timeout after ${timeoutMs}ms`));
      }, timeoutMs);

      // Store resolver
      this.pendingRequests.set(requestId, { resolve: promiseResolve, reject: promiseReject, timeout });

      // Send request
      const request = {
        id: requestId,
        path: absolutePath,
        key: keyValue
      };

      try {
        this.serverProcess.stdin.write(JSON.stringify(request) + '\n');
      } catch (err) {
        this.pendingRequests.delete(requestId);
        clearTimeout(timeout);
        promiseReject(err);
      }
    });
  }

  stop() {
    if (this.serverProcess) {
      this.serverProcess.kill();
      this.serverProcess = null;
      this.isReady = false;
    }
  }

  // Event emitter methods
  on(event, handler) {
    if (!this._handlers[event]) this._handlers[event] = [];
    this._handlers[event].push(handler);
  }

  once(event, handler) {
    const onceHandler = (...args) => {
      handler(...args);
      this.off(event, onceHandler);
    };
    this.on(event, onceHandler);
  }

  off(event, handler) {
    if (!this._handlers || !this._handlers[event]) return;
    this._handlers[event] = this._handlers[event].filter(h => h !== handler);
  }

  emit(event, ...args) {
    if (!this._handlers || !this._handlers[event]) return;
    this._handlers[event].forEach(handler => handler(...args));
  }
}

async function verifyKeyInFile(filePath, expectedKey, debug = false) {
  /**
   * Read key metadata from file using music-metadata
   * Returns the key value found in the file, or null if not found
   */
  try {
    const metadata = await parseFile(filePath);

    if (debug) {
      console.log('\n  Debug - All metadata:', JSON.stringify(metadata, null, 2));
    }

    // Try common fields first
    let key = metadata.common.key || metadata.common.initialKey;

    // Try native tag formats
    if (!key && metadata.native) {
      // ID3v2 (MP3, AIFF, WAV)
      const id3Key = metadata.native.ID3v2?.find(tag => tag.id === 'TKEY');
      if (id3Key) key = id3Key.value;

      // Vorbis comments (OGG, FLAC)
      if (!key) {
        const vorbisKey = metadata.native.vorbis?.find(tag => tag.id === 'KEY');
        if (vorbisKey) key = vorbisKey.value;
      }

      // iTunes/MP4 freeform tags
      if (!key) {
        const itunesKey = metadata.native.iTunes?.find(tag => tag.id === '----:com.apple.iTunes:KEY');
        if (itunesKey) key = itunesKey.value;
      }
    }

    // Handle buffer values (MP4/M4A freeform tags)
    if (key && Buffer.isBuffer(key)) {
      return key.toString('utf-8');
    }

    // Handle array values
    if (Array.isArray(key)) {
      return key[0];
    }

    return key || null;
  } catch (err) {
    console.error(`  Error reading metadata: ${err.message}`);
    return null;
  }
}

async function findTestFiles(testDir) {
  /**
   * Find test audio files in the specified directory
   */
  const testFiles = {};

  for (const format of FILE_FORMATS) {
    const filePath = resolve(testDir, `test.${format.ext}`);
    if (existsSync(filePath)) {
      testFiles[format.ext] = filePath;
    }
  }

  return testFiles;
}

async function runTests(serverPath, testFilesDir) {
  console.log('═══════════════════════════════════════════════════════');
  console.log('  Key Tagging Service Test Suite');
  console.log('═══════════════════════════════════════════════════════\n');

  // Find test files
  console.log(`Looking for test files in: ${testFilesDir}`);
  const testFiles = await findTestFiles(testFilesDir);

  if (Object.keys(testFiles).length === 0) {
    console.error('❌ No test files found!');
    console.error(`\nPlease add test audio files to: ${testFilesDir}`);
    console.error('Expected files: test.mp3, test.mp4, test.m4a, test.aac, test.aiff, test.aif, test.alac, test.wav, test.ogg, test.flac\n');
    process.exit(1);
  }

  console.log(`Found ${Object.keys(testFiles).length} test files:\n`);
  Object.entries(testFiles).forEach(([ext, path]) => {
    console.log(`  ✓ ${ext.toUpperCase().padEnd(6)} ${path}`);
  });
  console.log('');

  // Initialize service
  const service = new KeyTaggingService(serverPath);

  try {
    // Start server
    await service.start();

    // Test results
    const results = [];
    let keyIndex = Math.floor(Math.random() * TEST_KEYS.length);

    // Test each file format
    for (const [ext, filePath] of Object.entries(testFiles)) {
      const format = FILE_FORMATS.find(f => f.ext === ext);
      const testKey = TEST_KEYS[keyIndex % TEST_KEYS.length];
      keyIndex++;

      process.stdout.write(`Testing ${format.name.padEnd(6)} ... `);

      try {
        // Write key to file
        const writeResult = await service.tagFile(filePath, testKey);

        // Debug: Show write result
        // console.log(`\n  Write result:`, writeResult);

        // Verify by reading back
        // Increase delay to ensure file system flush and avoid music-metadata caching
        await new Promise(resolve => setTimeout(resolve, 500));
        const readKey = await verifyKeyInFile(filePath, testKey);

        if (readKey === testKey) {
          console.log(`✅ SUCCESS (wrote "${testKey}", read "${readKey}")`);
          results.push({ format: format.name, ext, success: true, key: testKey });
        } else {
          console.log(`⚠️  MISMATCH (wrote "${testKey}", read "${readKey || 'null'}")`);
          console.log(`    Server response:`, writeResult);
          results.push({ format: format.name, ext, success: false, key: testKey, readKey, error: 'Key mismatch' });
        }
      } catch (err) {
        console.log(`❌ FAILED (${err.message})`);
        results.push({ format: format.name, ext, success: false, key: testKey, error: err.message });
      }
    }

    // Print summary
    console.log('\n═══════════════════════════════════════════════════════');
    console.log('  Test Summary');
    console.log('═══════════════════════════════════════════════════════\n');

    const successful = results.filter(r => r.success).length;
    const total = results.length;

    console.log(`Total: ${total} tests`);
    console.log(`Passed: ${successful} ✅`);
    console.log(`Failed: ${total - successful} ❌`);
    console.log(`Success Rate: ${((successful / total) * 100).toFixed(1)}%\n`);

    if (successful < total) {
      console.log('Failed tests:');
      results.filter(r => !r.success).forEach(r => {
        console.log(`  • ${r.format}: ${r.error}`);
      });
      console.log('');
    }

    // Stop server
    service.stop();

    process.exit(successful === total ? 0 : 1);

  } catch (err) {
    console.error('Test failed:', err);
    service.stop();
    process.exit(1);
  }
}

// Main execution
const serverPath = process.argv[2] || '../tag_keys_server.py';
const testFilesDir = process.argv[3] || './test-files';

runTests(serverPath, testFilesDir);
