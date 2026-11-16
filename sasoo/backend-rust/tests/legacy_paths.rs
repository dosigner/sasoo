use std::{collections::BTreeMap, path::PathBuf};

use sasoo_backend::storage::paths::{ModeKind, Platform, RuntimeEnv, resolve_paths};

fn env() -> RuntimeEnv {
    RuntimeEnv {
        app_data_root: None,
        home: PathBuf::from("/fixture/home"),
        appdata: None,
        xdg_data_home: None,
        production: false,
        backend_source_dir: PathBuf::from("/fixture/sasoo/backend"),
        settings: BTreeMap::new(),
    }
}

#[test]
fn development_paths_keep_python_library_and_fallback() {
    let mut env = env();
    env.settings
        .insert("library_path_darwin".into(), "/fixture/custom".into());
    env.settings
        .insert("library_path".into(), "/fixture/old".into());
    let paths = resolve_paths(&env, Platform::MacOs, ModeKind::Worker).unwrap();
    assert_eq!(
        paths.app_data_root,
        PathBuf::from("/fixture/sasoo/backend/library")
    );
    assert_eq!(paths.db_path, paths.app_data_root.join("sasoo.db"));
    assert_eq!(paths.library_root, PathBuf::from("/fixture/custom"));
    assert_eq!(
        paths.library_search_roots,
        vec![PathBuf::from("/fixture/custom"), paths.default_library_root]
    );
    assert!(!PathBuf::from("/fixture/custom").exists());
}

#[test]
fn foreign_or_relative_stored_paths_fall_back_without_creating_directories() {
    for stored in [
        "relative/library",
        "C:\\Users\\name\\library",
        "/fixture/C:\\Users\\name\\library",
    ] {
        let mut env = env();
        env.settings
            .insert("library_path_darwin".into(), stored.into());
        env.settings
            .insert("library_path".into(), "/fixture/legacy".into());
        let paths = resolve_paths(&env, Platform::MacOs, ModeKind::Server).unwrap();
        assert_eq!(paths.library_root, PathBuf::from("/fixture/legacy"));
    }
}

#[test]
fn production_defaults_and_explicit_app_root_match_python() {
    let mut env = env();
    env.production = true;
    let mac = resolve_paths(&env, Platform::MacOs, ModeKind::Server).unwrap();
    assert_eq!(
        mac.app_data_root,
        PathBuf::from("/fixture/home/Library/Application Support/Sasoo")
    );
    assert_eq!(mac.default_library_root, mac.app_data_root.join("library"));
    env.xdg_data_home = Some(PathBuf::from("/fixture/xdg"));
    let linux = resolve_paths(&env, Platform::Linux, ModeKind::ReadOnly).unwrap();
    assert_eq!(linux.app_data_root, PathBuf::from("/fixture/xdg/Sasoo"));
    env.app_data_root = Some(PathBuf::from("~/isolated/../state"));
    let explicit = resolve_paths(&env, Platform::Linux, ModeKind::Worker).unwrap();
    assert_eq!(explicit.app_data_root, PathBuf::from("/fixture/home/state"));
    env.app_data_root = Some(PathBuf::from("relative"));
    assert!(resolve_paths(&env, Platform::Linux, ModeKind::Server).is_err());
}

#[test]
fn windows_paths_are_evaluated_as_windows_even_in_posix_fixture() {
    let mut env = env();
    env.production = true;
    env.home = PathBuf::from("C:\\Users\\fixture");
    env.appdata = Some(PathBuf::from("D:\\Roaming"));
    env.settings
        .insert("library_path_win32".into(), "/Users/foreign/library".into());
    env.settings
        .insert("library_path".into(), "E:\\논문\\library".into());
    let paths = resolve_paths(&env, Platform::Windows, ModeKind::Server).unwrap();
    assert_eq!(paths.app_data_root, PathBuf::from("D:\\Roaming\\Sasoo"));
    assert_eq!(paths.library_root, PathBuf::from("E:\\논문\\library"));
    assert_eq!(paths.library_search_roots.len(), 2);
}

#[test]
fn default_root_is_not_duplicated() {
    let env = env();
    let paths = resolve_paths(&env, Platform::Linux, ModeKind::Worker).unwrap();
    assert_eq!(paths.library_search_roots, vec![paths.default_library_root]);
}

#[cfg(unix)]
#[test]
fn explicit_root_resolves_symlinks_before_parent_and_keeps_missing_suffix() {
    let dir = tempfile::TempDir::new().unwrap();
    let root = dir.path().join("root");
    let external = dir.path().join("external");
    std::fs::create_dir_all(&root).unwrap();
    std::fs::create_dir_all(external.join("child")).unwrap();
    std::os::unix::fs::symlink(external.join("child"), root.join("alias")).unwrap();
    let input = root.join("alias/../state/missing");
    let mut env = env();
    env.app_data_root = Some(input.clone());
    let platform = if cfg!(target_os = "macos") {
        Platform::MacOs
    } else {
        Platform::Linux
    };
    let resolved = resolve_paths(&env, platform, ModeKind::Worker).unwrap();
    let output = std::process::Command::new("python3")
        .arg("-c")
        .arg("from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=False))")
        .arg(&input)
        .output()
        .unwrap();
    assert!(output.status.success());
    let python = PathBuf::from(String::from_utf8(output.stdout).unwrap().trim());
    assert_eq!(resolved.app_data_root, python);
    assert!(!external.join("state").exists());
    assert!(!root.join("state").exists());
}
