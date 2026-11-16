#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const sha256 = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');
const isHash = (value) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

function hashFile(filename) {
  const fd = fs.openSync(filename, 'r');
  try {
    const hash = crypto.createHash('sha256');
    const chunk = Buffer.allocUnsafe(1024 * 1024);
    let bytes = 0;
    let count;
    while ((count = fs.readSync(fd, chunk, 0, chunk.length, null)) > 0) {
      hash.update(chunk.subarray(0, count));
      bytes += count;
    }
    return { sha256: hash.digest('hex'), bytes };
  } finally { fs.closeSync(fd); }
}

function verifyResources(manifest, target, profileName, resourceRoot) {
  const errors = [];
  const verified = [];
  const fail = (code, resource, detail) => errors.push({ code, resource, detail });
  const profile = manifest.profiles?.[profileName];
  if (manifest.format_version !== 1) fail('invalid_manifest_version', null, 'Expected format_version=1.');
  if (manifest.download_policy !== 'forbidden') fail('downloads_not_disabled', null, 'Set download_policy to forbidden.');
  if (!target || !profileName || !resourceRoot) fail('missing_selection', null, 'Select a target, profile, and resource root.');
  if (!profile) fail('unknown_profile', profileName, 'Use an explicitly declared profile.');
  if (profile?.requirements_complete !== true) fail('resource_inventory_incomplete', profileName, 'Resolve every native/model dependency before use.');
  if (!Array.isArray(profile?.required_resources) || profile.required_resources.length === 0) {
    fail('empty_resource_inventory', profileName, 'A profile must declare its required files.');
  }
  const resources = new Map();
  for (const resource of manifest.resources || []) {
    if (!resource || typeof resource.id !== 'string' || resources.has(resource.id)) {
      fail('invalid_resource_id', resource?.id ?? null, 'Resource IDs must be unique strings.');
      continue;
    }
    resources.set(resource.id, resource);
  }
  let canonicalRoot;
  try { canonicalRoot = fs.realpathSync(resourceRoot); }
  catch { fail('missing_resource_root', null, 'Provide the approved local resource cache. No download is attempted.'); }
  for (const id of profile?.required_resources || []) {
    const resource = resources.get(id);
    if (!resource) { fail('undeclared_resource', id, 'Add a complete manifest entry.'); continue; }
    for (const field of ['origin_url', 'revision', 'filename', 'license', 'load_path']) {
      if (typeof resource[field] !== 'string' || !resource[field].trim()) fail('missing_metadata', id, `Missing ${field}.`);
    }
    if (!isHash(resource.sha256)) fail('unpinned_resource', id, 'A full SHA-256 is required; a commit or filename is insufficient.');
    if (resource.download_policy !== 'forbidden') fail('resource_downloads_not_disabled', id, 'Automatic downloads must be disabled.');
    if (!Array.isArray(resource.targets) || !resource.targets.includes(target)) fail('target_unverified', id, `No file declaration for ${target}.`);
    const relative = resource.load_path;
    if (typeof relative !== 'string' || !relative || path.isAbsolute(relative) || relative.includes('\\') || relative.split('/').includes('..')) {
      fail('unsafe_load_path', id, 'load_path must stay within the approved resource root.');
      continue;
    }
    if (!canonicalRoot) continue;
    try {
      const candidate = fs.realpathSync(path.join(canonicalRoot, relative));
      const inside = path.relative(canonicalRoot, candidate);
      if (!inside || inside.startsWith(`..${path.sep}`) || inside === '..' || path.isAbsolute(inside)) {
        fail('resource_outside_root', id, 'Resolved files, including symlinks, must stay in the resource root.');
        continue;
      }
      if (!fs.statSync(candidate).isFile()) { fail('resource_not_file', id, 'Expected a regular file.'); continue; }
      const measured = hashFile(candidate);
      if (measured.sha256 !== resource.sha256) fail('hash_mismatch', id, 'The local file differs from the declared SHA-256.');
      else verified.push({ id, ...measured, load_path: relative });
    } catch (error) {
      fail('missing_or_unreadable_resource', id, `Provide the pinned local file (${error.code || 'read error'}).`);
    }
  }
  return {
    format_version: 1,
    profile: profileName,
    target,
    resource_status: errors.length ? 'blocked' : 'verified',
    deployment_status: 'not_evaluated',
    network_requests: 0,
    verified,
    errors,
  };
}

function selfTest() {
  const assert = require('node:assert/strict');
  const os = require('node:os');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'sasoo-resource-contract-'));
  const resourceRoot = path.join(root, 'cache');
  fs.mkdirSync(resourceRoot);
  const bytes = Buffer.from('synthetic resource integrity fixture\n');
  fs.writeFileSync(path.join(resourceRoot, 'native.bin'), bytes);
  const manifest = {
    format_version: 1, download_policy: 'forbidden',
    profiles: { native: { requirements_complete: true, required_resources: ['native'] } },
    resources: [{ id: 'native', origin_url: 'https://example.invalid/synthetic', revision: 'synthetic-v1',
      filename: 'native.bin', sha256: sha256(bytes), license: 'synthetic-test-only',
      targets: ['synthetic-target'], load_path: 'native.bin', download_policy: 'forbidden' }],
  };
  let tests = 0;
  const check = (change, code) => {
    const candidate = structuredClone(manifest);
    change(candidate);
    const receipt = verifyResources(candidate, 'synthetic-target', 'native', resourceRoot);
    assert.equal(receipt.resource_status, 'blocked');
    assert(receipt.errors.some((error) => error.code === code), JSON.stringify(receipt));
    assert.equal(receipt.network_requests, 0);
    tests++;
  };
  try {
    const valid = verifyResources(manifest, 'synthetic-target', 'native', resourceRoot);
    assert.equal(valid.resource_status, 'verified');
    assert.equal(valid.deployment_status, 'not_evaluated');
    assert.equal(valid.verified[0].sha256, sha256(bytes));
    tests++;
    check((m) => { m.resources[0].license = null; }, 'missing_metadata');
    check((m) => { m.resources[0].sha256 = null; }, 'unpinned_resource');
    check((m) => { m.resources[0].load_path = 'missing.bin'; }, 'missing_or_unreadable_resource');
    check((m) => { m.resources[0].sha256 = '0'.repeat(64); }, 'hash_mismatch');
    check((m) => { m.resources[0].targets = ['another-target']; }, 'target_unverified');
    check((m) => { m.download_policy = 'allowed'; }, 'downloads_not_disabled');
    check((m) => { m.resources[0].download_policy = 'allowed'; }, 'resource_downloads_not_disabled');
    check((m) => { m.resources[0].load_path = '../outside.bin'; }, 'unsafe_load_path');
    check((m) => { m.profiles.native.requirements_complete = false; }, 'resource_inventory_incomplete');
    check((m) => { m.profiles.native.required_resources = []; }, 'empty_resource_inventory');
    check((m) => { m.profiles.native.required_resources = ['absent']; }, 'undeclared_resource');
    check((m) => { m.resources.push(structuredClone(m.resources[0])); }, 'invalid_resource_id');
    fs.writeFileSync(path.join(root, 'outside.bin'), bytes);
    fs.symlinkSync(path.join(root, 'outside.bin'), path.join(resourceRoot, 'escaped.bin'));
    check((m) => { m.resources[0].load_path = 'escaped.bin'; }, 'resource_outside_root');
    return { status: 'passed', tests, network_requests: 0 };
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

function main(argv) {
  if (argv.length === 1 && argv[0] === '--self-test') { console.log(JSON.stringify(selfTest())); return; }
  const options = {};
  const allowed = new Set(['--manifest', '--target', '--profile', '--resource-root']);
  for (let i = 0; i < argv.length; i += 2) {
    if (!allowed.has(argv[i]) || !argv[i + 1] || options[argv[i]]) throw new Error('Use --manifest PATH --target TARGET --profile PROFILE --resource-root PATH.');
    options[argv[i]] = argv[i + 1];
  }
  if (Object.keys(options).length !== 4) throw new Error('Use --manifest PATH --target TARGET --profile PROFILE --resource-root PATH.');
  const manifest = JSON.parse(fs.readFileSync(options['--manifest'], 'utf8'));
  const receipt = verifyResources(manifest, options['--target'], options['--profile'], options['--resource-root']);
  console.log(JSON.stringify(receipt, null, 2));
  if (receipt.resource_status === 'blocked') process.exitCode = 2;
}

if (require.main === module) {
  try { main(process.argv.slice(2)); }
  catch (error) { console.error(JSON.stringify({ error: error.message })); process.exitCode = 1; }
}

module.exports = { verifyResources };
