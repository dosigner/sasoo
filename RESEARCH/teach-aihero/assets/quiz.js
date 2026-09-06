// 공용 퀴즈 위젯 — .quiz 블록 안의 radio 선택에 즉시 피드백을 준다.
// 사용법: <div class="quiz" data-answer="b"> 안에 name이 고유한 radio들과 <p class="feedback"></p>를 둔다.
document.addEventListener('change', (e) => {
  const quiz = e.target.closest('.quiz');
  if (!quiz || e.target.type !== 'radio') return;
  const fb = quiz.querySelector('.feedback');
  const right = e.target.value === quiz.dataset.answer;
  fb.textContent = right ? '정답입니다. ' + (quiz.dataset.why || '') : '아직입니다. 지도를 다시 떠올려 보세요.';
  fb.className = 'feedback ' + (right ? 'ok' : 'no');
});
