#[path = "../tests/support/library_fixture.rs"]
mod fixture;

fn main() {
    let root = tempfile::Builder::new()
        .prefix("sasoo-readonly-")
        .tempdir()
        .expect("Create disposable fixture root");
    fixture::seed(root.path(), true);
    println!("{}", root.keep().display());
}
