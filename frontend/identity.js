const college = document.getElementById("college");
const grade = document.getElementById("grade");
const role = document.getElementById("role");
const tags = document.getElementById("tags");
const saveInfo = document.getElementById("saveInfo");

const savedProfile = localStorage.getItem("agent_profile");
if (savedProfile) {
  const profile = JSON.parse(savedProfile);
  if (profile.college) {
    college.value = profile.college;
  }
  if (profile.grade) {
    grade.value = profile.grade;
  }
  if (profile.role) {
    role.value = profile.role;
  }
  if (profile.tags) {
    tags.value = profile.tags;
  }
}

document.getElementById("saveProfile").addEventListener("click", () => {
  const profile = {
    college: college.value,
    grade: grade.value,
    role: role.value,
    tags: tags.value.trim()
  };
  localStorage.setItem("agent_profile", JSON.stringify(profile));
  saveInfo.textContent = "身份标签已保存，可用于后续对话RAG检索。";
});
