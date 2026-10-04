import axios from "axios";
import React from "react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { toaster } from "../../components/ui/toaster"
import Card from "../../components/ui/Card";
import Button from "../../components/ui/Button";


const Gallery = () => {
  const [gallery, setGallery] = useState([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(16);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const navigate = useNavigate();

  const fetchGallery = async () => {
    const token = localStorage.getItem("token");
    setLoading(true);
    setError(false);

    try {
      const res = await axios.get(`/api/gallery/`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
        params: {
          page: page,
          page_size: pageSize,
        },
      });

      setGallery(res.data.images);
      setPage(res.data.page);
      setPageSize(res.data.page_size);
      setTotalPages(res.data.total_pages);
    } catch {
      setError(true);
      toaster.create({
        title: "Error",
        description: "Unable to load gallery.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchGallery();
  }, [page]);

  const handlePageChange = (nextPage) => {
    if (nextPage < 0)
      setPage(0);
    else if (nextPage > totalPages)
      setPage(totalPages);
    else
      setPage(nextPage);
  }

  const handleDelete = async (imageId) => {
    const token = localStorage.getItem("token");

    try {
      await axios.delete(`/api/gallery/${imageId}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      toaster.create({
        title: "Deleted",
        description: "Image deleted successfully.",
        status: "success",
        duration: 3000,
        isClosable: true,
      });
      setGallery(gallery.filter((img) => img.id !== imageId));
    } catch {
      toaster.create({
        title: "Error",
        description: "Failed to delete image.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    }
  };

  const handleRedirect = (img, mode) => {
    localStorage.setItem("selectedImage", JSON.stringify(img));
    navigate(`/views/workflows/${mode}`);
  };

  return (

    <div className="w-full min-h-screen flex flex-col p-5 gap-5">
      <h1 className="font-bold text-3xl">Your Gallery</h1>
      <div className="flex flex-wrap justify-center gap-5">
        {loading ? (
          <div className="w-full h-[50vh] flex flex-col items-center justify-center gap-4">
            <h1 className="text-2xl font-bold text-center m-0 text-muted">
              Loading gallery...
            </h1>
          </div>
        ) : error ? (
          <div className="w-full h-[50vh] flex flex-col items-center justify-center gap-4">
            <h1 className="text-2xl font-bold text-center m-0">
              Couldn't load your gallery
            </h1>
            <Button variant="outline" onClick={fetchGallery}>Try again</Button>
          </div>
        ) : (!gallery || gallery.length === 0) ? (
          <div className="w-full h-[50vh] flex flex-col items-center justify-center gap-4">
            <h1 className="text-2xl font-bold text-center m-0 text-muted">
              No images yet
            </h1>
          </div>
        ) : (
          gallery.map((img) => (
            <Card
              key={img.id}
              className="w-[300px] p-3 flex flex-col justify-between"
            >
              <img
                src={`data:image/png;base64,${img.image_base64}`}
                alt="generated"
                className="w-full rounded-md mb-3 "
              />
              <div className="flex flex-col text-sm space-y-1.5 items-start flex-grow">
                <p><b>Model:</b> {img.model}</p>
                <p><b>Mode:</b> {img.mode}</p>
                <p><b>Size:</b> {img.width} × {img.height}</p>
                {img.mode != "inpainting" && img.mode != "text2img" && img.mode != "furniture-replace" && (
                  <p><b>Scaling mode:</b> {img.scaling_mode}</p>
                )}
                <p><b>Prompt:</b> {img.prompt}</p>
                <p><b>Seed:</b> {img.seed}</p>
                <p><b>Guidance:</b> {img.guidance_scale}</p>

                {img.mode == "controlnet" && (
                  <>
                    <p><b>Canny low threshold:</b> {img.canny_low_threshold}</p>
                    <p><b>Canny high threshold:</b> {img.canny_high_threshold}</p>
                  </>
                )}

                {img.mode == "outpainting" && (
                  <>
                    <p><b>Pad left:</b> {img.pad_left}</p>
                    <p><b>Pad right:</b> {img.pad_right}</p>
                    <p><b>Pad top:</b> {img.pad_top}</p>
                    <p><b>Pad bottom:</b> {img.pad_bottom}</p>
                  </>
                )}

                <p><b>Created:</b> {new Date(img.created_at).toLocaleString()}</p>
              </div>
              <div className="flex flex-col mt-3 space-y-2">
                <button
                  className="bg-foreground/5 hover:bg-foreground/10 text-xs text-foreground rounded p-1.5 transition-colors cursor-pointer"
                  onClick={() => handleRedirect(img, "text-to-image")}
                >
                  Use in Text2Image
                </button>
                <button
                  className="bg-foreground/5 hover:bg-foreground/10 text-xs text-foreground rounded p-1.5 transition-colors cursor-pointer"
                  onClick={() => handleRedirect(img, "image-to-image")}
                >
                  Use in Img2Img
                </button>
                <button
                  className="bg-foreground/5 hover:bg-foreground/10 text-xs text-foreground rounded p-1.5 transition-colors cursor-pointer"
                  onClick={() => handleRedirect(img, "inpainting")}
                >
                  Use in Inpainting
                </button>
                <button
                  className="bg-foreground/5 hover:bg-foreground/10 text-xs text-foreground rounded p-1.5 transition-colors cursor-pointer"
                  onClick={() => handleRedirect(img, "furniture-replace")}
                >
                  Use in Furniture Replace
                </button>
                <button
                  className="bg-foreground/5 hover:bg-foreground/10 text-xs text-foreground rounded p-1.5 transition-colors cursor-pointer"
                  onClick={() => handleRedirect(img, "control-net")}
                >
                  Use in Control Net
                </button>
                <button
                  className="bg-foreground/5 hover:bg-foreground/10 text-xs text-foreground rounded p-1.5 transition-colors cursor-pointer"
                  onClick={() => handleRedirect(img, "outpainting")}
                >
                  Use in Outpainting
                </button>
                <button
                  className="bg-[#f3e3df] hover:bg-[#ecd5cf] text-xs text-[#7a3b2e] rounded p-1.5 transition-colors cursor-pointer"
                  onClick={() => handleDelete(img.id)}
                >
                  Delete
                </button>
              </div>
            </Card>
          ))
        )}
      </div>

      <div className="flex justify-center items-center gap-4 mt-5">
        <button
          className="bg-foreground/10 hover:bg-foreground/15 rounded px-3 py-1 disabled:opacity-50 transition-colors cursor-pointer"
          onClick={() => handlePageChange(page - 1)}
          disabled={page === 1 || loading}
        >
          Previous
        </button>

        <span className="text-muted">Page </span>
        <select
          value={page}
          onChange={(e) => handlePageChange(Number(e.target.value))}
          className="border border-foreground/15 rounded px-2 py-1 max-h-40 overflow-y-auto disabled:opacity-50 bg-transparent"
          disabled={loading}
        >
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <span className="text-muted"> of {totalPages}</span>

        <button
          className="bg-foreground/10 hover:bg-foreground/15 rounded px-3 py-1 disabled:opacity-50 transition-colors cursor-pointer"
          onClick={() => handlePageChange(page + 1)}
          disabled={page === totalPages || loading}
        >
          Next
        </button>
      </div>

    </div>

  );
};

export default Gallery;
