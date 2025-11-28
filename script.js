function toggleSidebar() {
    let bar = document.getElementById("sidebar");

    if (bar.style.width === "200px") {
        bar.style.width = "0";
    } else {
        bar.style.width = "200px";
    }
}
