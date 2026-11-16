use std::{
    collections::{BTreeMap, HashSet},
    path::{Component, Path, PathBuf},
};

use crate::error::{Result, SasooError};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Platform {
    MacOs,
    Windows,
    Linux,
}

impl Platform {
    pub fn setting_key(self) -> &'static str {
        match self {
            Self::MacOs => "library_path_darwin",
            Self::Windows => "library_path_win32",
            Self::Linux => "library_path_linux",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ModeKind {
    Server,
    Worker,
    ReadOnly,
}

#[derive(Clone, Debug)]
pub struct RuntimeEnv {
    pub app_data_root: Option<PathBuf>,
    pub home: PathBuf,
    pub appdata: Option<PathBuf>,
    pub xdg_data_home: Option<PathBuf>,
    pub production: bool,
    pub backend_source_dir: PathBuf,
    pub settings: BTreeMap<String, String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimePaths {
    pub app_data_root: PathBuf,
    pub db_path: PathBuf,
    pub config_path: PathBuf,
    pub default_library_root: PathBuf,
    pub library_root: PathBuf,
    pub library_search_roots: Vec<PathBuf>,
    pub owner_lock_path: PathBuf,
}

fn join(base: &Path, part: &str, platform: Platform) -> PathBuf {
    if platform == Platform::Windows {
        PathBuf::from(format!(
            "{}\\{}",
            base.to_string_lossy().trim_end_matches(['\\', '/']),
            part.replace('/', "\\")
        ))
    } else {
        base.join(part)
    }
}

fn foreign_windows_syntax(text: &str) -> bool {
    text.contains('\\')
        || text
            .as_bytes()
            .windows(3)
            .any(|w| w[0].is_ascii_alphabetic() && w[1] == b':' && matches!(w[2], b'/' | b'\\'))
}

fn is_absolute(text: &str, platform: Platform) -> bool {
    if platform == Platform::Windows {
        let bytes = text.as_bytes();
        let drive = bytes.len() >= 3
            && bytes[0].is_ascii_alphabetic()
            && bytes[1] == b':'
            && matches!(bytes[2], b'/' | b'\\');
        let unc = text.starts_with("\\\\") || text.starts_with("//");
        drive
            || unc
                && text
                    .trim_start_matches(['\\', '/'])
                    .split(['\\', '/'])
                    .filter(|part| !part.is_empty())
                    .count()
                    >= 2
    } else {
        text.starts_with('/') && !foreign_windows_syntax(text)
    }
}

fn expand_home(text: &str, home: &Path, platform: Platform) -> String {
    if text == "~" {
        return home.to_string_lossy().into_owned();
    }
    if let Some(rest) = text.strip_prefix("~/").or_else(|| {
        if platform == Platform::Windows {
            text.strip_prefix("~\\")
        } else {
            None
        }
    }) {
        return join(home, rest, platform).to_string_lossy().into_owned();
    }
    text.to_owned()
}

fn normalize_absolute(text: &str, platform: Platform) -> PathBuf {
    if platform == Platform::Windows {
        let text = text.replace('/', "\\");
        let (prefix, body, protected) = if text.starts_with("\\\\") {
            ("\\\\".to_owned(), text.trim_start_matches('\\'), 2)
        } else {
            (text[..3].to_owned(), &text[3..], 0)
        };
        let mut parts = Vec::new();
        for part in body.split('\\') {
            match part {
                "" | "." => {}
                ".." if parts.len() > protected => {
                    parts.pop();
                }
                ".." => {}
                other => parts.push(other),
            }
        }
        PathBuf::from(format!("{prefix}{}", parts.join("\\")))
    } else {
        let mut normalized = PathBuf::new();
        for component in Path::new(text).components() {
            match component {
                Component::ParentDir => {
                    normalized.pop();
                }
                Component::CurDir => {}
                other => normalized.push(other.as_os_str()),
            }
        }
        normalized
    }
}

fn is_host_platform(platform: Platform) -> bool {
    matches!(
        (platform, std::env::consts::OS),
        (Platform::MacOs, "macos") | (Platform::Windows, "windows") | (Platform::Linux, "linux")
    )
}

fn resolve_host_path(path: &Path, active_links: &mut HashSet<PathBuf>) -> Result<PathBuf> {
    let mut resolved = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                resolved.pop();
            }
            Component::Normal(name) => {
                resolved.push(name);
                match std::fs::symlink_metadata(&resolved) {
                    Ok(metadata) if metadata.file_type().is_symlink() => {
                        let link = resolved.clone();
                        if !active_links.insert(link.clone()) {
                            return Err(SasooError::InvalidInput(
                                "App data root contains a symbolic-link cycle".into(),
                            ));
                        }
                        let target = std::fs::read_link(&link)?;
                        let target = if target.is_absolute() {
                            target
                        } else {
                            link.parent().unwrap_or(Path::new("/")).join(target)
                        };
                        resolved = resolve_host_path(&target, active_links)?;
                        active_links.remove(&link);
                    }
                    Ok(_) => {}
                    Err(error)
                        if matches!(
                            error.kind(),
                            std::io::ErrorKind::NotFound | std::io::ErrorKind::NotADirectory
                        ) => {}
                    Err(error) => return Err(error.into()),
                }
            }
            other => resolved.push(other.as_os_str()),
        }
    }
    Ok(resolved)
}

pub fn usable_library_path(raw: &str, home: &Path, platform: Platform) -> Option<PathBuf> {
    let text = expand_home(raw.trim(), home, platform);
    is_absolute(&text, platform).then(|| PathBuf::from(text))
}

/// Resolve path syntax without opening a database or creating directories.
pub fn resolve_paths(
    env: &RuntimeEnv,
    platform: Platform,
    _mode: ModeKind,
) -> Result<RuntimePaths> {
    let explicit = env
        .app_data_root
        .as_ref()
        .filter(|value| !value.to_string_lossy().trim().is_empty());
    let app_data_root = if let Some(explicit) = explicit {
        let text = expand_home(explicit.to_string_lossy().trim(), &env.home, platform);
        if !is_absolute(&text, platform) {
            return Err(SasooError::InvalidInput(
                "SASOO_APP_DATA_ROOT must be an absolute path for this platform".into(),
            ));
        }
        if is_host_platform(platform) {
            resolve_host_path(Path::new(&text), &mut HashSet::new())?
        } else {
            normalize_absolute(&text, platform)
        }
    } else if env.production {
        let base = match platform {
            Platform::MacOs => join(&env.home, "Library/Application Support", platform),
            Platform::Windows => env
                .appdata
                .clone()
                .unwrap_or_else(|| join(&env.home, "AppData/Roaming", platform)),
            Platform::Linux => env
                .xdg_data_home
                .clone()
                .unwrap_or_else(|| join(&env.home, ".local/share", platform)),
        };
        join(&base, "Sasoo", platform)
    } else {
        join(&env.backend_source_dir, "library", platform)
    };
    if !is_absolute(&app_data_root.to_string_lossy(), platform) {
        return Err(SasooError::InvalidInput(
            "Resolved app data root must be absolute".into(),
        ));
    }
    let default_library_root = if env.production {
        join(&app_data_root, "library", platform)
    } else {
        join(&env.backend_source_dir, "library", platform)
    };
    let library_root = [platform.setting_key(), "library_path"]
        .into_iter()
        .find_map(|key| usable_library_path(env.settings.get(key)?, &env.home, platform))
        .unwrap_or_else(|| default_library_root.clone());
    let mut library_search_roots = vec![library_root.clone()];
    if default_library_root != library_root {
        library_search_roots.push(default_library_root.clone());
    }
    Ok(RuntimePaths {
        db_path: join(&app_data_root, "sasoo.db", platform),
        config_path: join(&app_data_root, "config.json", platform),
        owner_lock_path: join(&app_data_root, "sasoo.db.runtime-owner.lock", platform),
        app_data_root,
        default_library_root,
        library_root,
        library_search_roots,
    })
}
