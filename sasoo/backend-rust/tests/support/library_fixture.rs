use serde_json::json;
use std::{fs, path::Path, time::UNIX_EPOCH};

pub fn seed(root: &Path, context_column: bool) {
    fs::create_dir_all(root.join("library/one/figures")).unwrap();
    fs::write(
        root.join(".sasoo-rust-isolated-fixture"),
        "synthetic-only\n",
    )
    .unwrap();
    let pdf = root.join("library/one/paper.pdf");
    fs::write(&pdf, minimal_pdf()).unwrap();
    fs::write(root.join("library/one/figures/figure.svg"), "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"240\" height=\"120\"><rect width=\"240\" height=\"120\" fill=\"#eef\"/><text x=\"20\" y=\"65\">Synthetic figure</text></svg>").unwrap();
    fs::write(
        root.join("library/one/table.csv"),
        "power_mW,efficiency\n10,0.8\n",
    )
    .unwrap();
    let meta = pdf.metadata().unwrap();
    let signature = json!({"pdf_size":meta.len(),"pdf_mtime_ns":meta.modified().unwrap().duration_since(UNIX_EPOCH).unwrap().as_nanos() as u64});
    let full_text = "--- Page 1 ---\n\n1 Introduction\n\nSynthetic optics paper: efficiency is 0.8 at 10 mW.\n\nTable 1: Power and efficiency.";
    let mut manifest = json!({"parser_version":"odl-v3","full_text":full_text,"visual_artifacts_ready":true,"figures":[{"file_path":"figures/figure.svg"}],"tables":[{"csv_path":"table.csv"}]});
    for key in ["pdf_size", "pdf_mtime_ns"] {
        manifest[key] = signature[key].clone();
    }
    fs::write(
        root.join("library/one/.odl_manifest.json"),
        serde_json::to_vec(&manifest).unwrap(),
    )
    .unwrap();
    fs::write(root.join("library/one/.document_context.json"), serde_json::to_vec(&json!({"parser_version":"odl-v3","context_builder_version":"document-context-v4","pdf_signature":signature,"full_text":full_text,"sections":{},"phase_inputs":{}})).unwrap()).unwrap();
    let c = rusqlite::Connection::open(root.join("sasoo.db")).unwrap();
    c.execute_batch(include_str!("../fixtures/legacy/schema.sql"))
        .unwrap();
    if context_column {
        c.execute_batch("ALTER TABLE discussion_messages ADD COLUMN context_json TEXT")
            .unwrap();
    }
    c.execute_batch("INSERT INTO papers(id,title,authors,folder_name,notes,tags,status) VALUES(1,'합성 광학 논문','Fixture Author','one','보존할 메모','optics','completed'),(2,'다른 논문',NULL,'missing',NULL,NULL,'analyzing');
    INSERT INTO analysis_results(id,paper_id,phase,result,model_used,tokens_in,tokens_out,cost_usd,created_at) VALUES
    (10,1,'recipe','{\"title\":\"합성 레시피\",\"objective\":\"효율 확인\",\"parameters\":[{\"name\":\"power\",\"value\":\"10\",\"unit\":\"mW\"}],\"steps\":[]}', 'fixture',100,20,0.01,'2026-01-01'),
    (11,1,'screening','{\"summary\":\"저장된 요약\",\"domain\":\"optics\",\"key_topics\":[\"efficiency\"]}', 'fixture',NULL,NULL,NULL,'2026-01-02');
    INSERT INTO figures(id,paper_id,figure_num,caption,file_path,bbox_json,page_number,detailed_explanation,is_composite) VALUES(7,1,'1','합성 그림','/static/library/one/figures/figure.svg','[10,20,210,120]',1,'저장된 설명',0);
    INSERT INTO tables(id,paper_id,table_num,caption,csv_path,markdown_text,page_number) VALUES(8,1,'1','합성 표','/static/library/one/table.csv','| power | efficiency |\n| 10 mW | 0.8 |',1);
    INSERT INTO discussion_messages(id,paper_id,kind,content,status,tokens_in,tokens_out,cost_usd) VALUES(1,1,'user','효율은?','complete',NULL,NULL,NULL),(2,1,'sasoo','0.8이라고 저장돼 있어.','complete',100,10,0.01),(3,1,'sasoo','중단된 답변','interrupted',NULL,NULL,NULL);
    INSERT INTO settings(key,value) VALUES('theme','light'),('research_areas','[\"광학\"]'),('gemini_api_key','enc:v1:synthetic-unreadable'),('openai_api_key','synthetic-private-value'),('library_path','/outside/old/library');").unwrap();
    if context_column {
        c.execute("UPDATE discussion_messages SET context_json=?1 WHERE id=2", [json!({"sources":[{"key":"recipe","result_id":10,"chars":30,"label":"이전 레시피"}]}).to_string()]).unwrap();
    }
}

pub fn minimal_pdf() -> Vec<u8> {
    let stream = "BT /F1 18 Tf 60 720 Td (Synthetic optics paper) Tj 0 -32 Td /F1 12 Tf (Efficiency is 0.8 at 10 mW.) Tj ET";
    let objects = ["<< /Type /Catalog /Pages 2 0 R >>".to_owned(), "<< /Type /Pages /Kids [3 0 R] /Count 1 >>".into(), "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>".into(), "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>".into(), format!("<< /Length {} >>\nstream\n{stream}\nendstream", stream.len())];
    let mut pdf = "%PDF-1.4\n".to_owned();
    let mut offsets = vec![0];
    for (i, object) in objects.iter().enumerate() {
        offsets.push(pdf.len());
        pdf.push_str(&format!("{} 0 obj\n{object}\nendobj\n", i + 1));
    }
    let xref = pdf.len();
    pdf.push_str("xref\n0 6\n0000000000 65535 f \n");
    for offset in &offsets[1..] {
        pdf.push_str(&format!("{offset:010} 00000 n \n"));
    }
    pdf.push_str(&format!(
        "trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ));
    pdf.into_bytes()
}
