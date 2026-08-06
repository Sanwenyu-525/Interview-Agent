use std::path::Path;
use std::process::Command;

#[tauri::command]
fn open_project_directory(path: String) -> Result<(), String> {
  if !Path::new(&path).exists() {
    return Err(format!("项目目录不存在: {path}"));
  }

  #[cfg(target_os = "windows")]
  Command::new("explorer")
    .arg(&path)
    .spawn()
    .map_err(|error| format!("无法打开项目目录: {error}"))?;

  #[cfg(target_os = "macos")]
  Command::new("open")
    .arg(&path)
    .spawn()
    .map_err(|error| format!("无法打开项目目录: {error}"))?;

  #[cfg(all(unix, not(target_os = "macos")))]
  Command::new("xdg-open")
    .arg(&path)
    .spawn()
    .map_err(|error| format!("无法打开项目目录: {error}"))?;

  Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      Ok(())
    })
    .invoke_handler(tauri::generate_handler![open_project_directory])
    .run(tauri::generate_context!())
    .expect("error while running application");
}
